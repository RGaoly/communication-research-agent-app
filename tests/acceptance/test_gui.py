import json
from pathlib import Path
import re
import threading
import urllib.request
import urllib.error

import pytest

from cra_engine.common import EngineError, digest
from cra_engine.gui import Gateway, make_server, validate_config


def config():
    return {"base_url":"https://api.deepseek.com/v1", "model":"deepseek-flash", "max_tokens":256,"input_price":.30,"output_price":1.20,"budget":5,"deepseek_pricing":True}


@pytest.fixture
def gateway(tmp_path, monkeypatch):
    monkeypatch.setattr("cra_engine.gui.public_destination",lambda _: None)
    service = Gateway(tmp_path)
    service.configure(config())
    calls = []
    def provider(url, hosts, **kwargs):
        calls.append(kwargs)
        return {"model":"deepseek-flash", "choices":[{"finish_reason":"stop","message":{"content":"Synthetic provider response"}}], "usage":{"prompt_tokens":10,"completion_tokens":5,"prompt_cache_hit_tokens":0,"prompt_cache_miss_tokens":10}}
    monkeypatch.setattr("cra_engine.gui.fetch_json",provider)
    return service, calls


def test_gui_key_never_stored_and_two_call_limit_survives_restart(gateway,tmp_path):
    service,calls=gateway
    key="TEST-KEY-DO-NOT-PERSIST"
    value={"api_key":key,"config_hash":digest(service.config),"prompt":"Synthetic evidence only"}
    assert service.request("test",value)["content"] == "Synthetic provider response"
    service.request("run",value)
    with pytest.raises(EngineError,match="额度"):service.request("run",value)
    assert len(calls)==2
    assert key not in (tmp_path/"gui-usage.sqlite").read_bytes().decode(errors="ignore")
    restarted=Gateway(tmp_path); restarted.configure(config())
    assert restarted.status()["calls"]==2
    with pytest.raises(EngineError):restarted.request("test",value)


def test_stale_form_never_sends_key_to_changed_endpoint(gateway):
    service,calls=gateway
    value={"api_key":"TEST ONLY","config_hash":digest(service.config)}
    changed=config();changed["model"]="other-model";service.configure(changed)
    with pytest.raises(EngineError,match="配置已变化"):service.request("test",value)
    assert not calls


def test_unknown_paid_request_prevents_retry(gateway,monkeypatch):
    service,calls=gateway
    def failed(*args,**kwargs): raise EngineError("Simulated unknown response")
    monkeypatch.setattr("cra_engine.gui.fetch_json",failed)
    value={"api_key":"TEST ONLY","config_hash":digest(service.config)}
    with pytest.raises(EngineError):service.request("test",value)
    assert service.status()["uncertain"]
    with pytest.raises(EngineError,match="核对"):service.request("run",value)


def test_gui_budget_and_sensitive_task_are_blocked_before_request(gateway):
    service,calls=gateway
    value={"api_key":"TEST ONLY","config_hash":digest(service.config)}
    service.request("test",value)
    value["prompt"]="Personal address respondent@example.invalid"
    with pytest.raises(EngineError):service.request("run",value)
    assert len(calls)==1
    tiny=config();tiny["budget"]=.000000001;service.configure(tiny)
    value.update(config_hash=digest(service.config),prompt="Synthetic example")
    with pytest.raises(EngineError,match="预算"):service.request("run",value)
    assert len(calls)==1


@pytest.mark.parametrize("url",["http://api.deepseek.com", "https://user:password@example.invalid", "https://example.invalid/?key=secret", "https://example.invalid:8080"])
def test_gui_rejects_unsafe_endpoints(url):
    cfg=config();cfg["base_url"]=url
    with pytest.raises(EngineError):validate_config(cfg)


def test_dns_proxy_compatibility_is_limited_to_authorized_official_host(monkeypatch):
    from cra_engine.gui import public_destination
    monkeypatch.setattr("cra_engine.gui.socket.getaddrinfo",lambda *a,**k:[(2,1,6,"",("198.18.0.37",443))])
    public_destination("https://api.deepseek.com/v1")
    with pytest.raises(EngineError):public_destination("https://custom.invalid/v1")
    monkeypatch.setattr("cra_engine.gui.socket.getaddrinfo",lambda *a,**k:[(2,1,6,"",("127.0.0.1",443))])
    with pytest.raises(EngineError):public_destination("https://api.deepseek.com/v1")


def test_gui_echoed_key_is_redacted_before_output(gateway,monkeypatch):
    service,_=gateway
    def response(*args,**kwargs):
        return {"model":"fixture","choices":[{"finish_reason":"stop","message":{"content":"KEY-ECHO-TEST"}}],"usage":{"prompt_tokens":10,"completion_tokens":5}}
    monkeypatch.setattr("cra_engine.gui.fetch_json",response)
    output=service.request("test",{"api_key":"KEY-ECHO-TEST","config_hash":digest(service.config)})
    assert output["content"]=="[REDACTED]"


def test_http_loopback_csrf_host_and_no_key_storage(tmp_path):
    server=make_server(tmp_path)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base="http://127.0.0.1:%s" % server.server_port
    try:
        response=urllib.request.urlopen(base)
        html=response.read().decode()
        assert "no-store" in response.headers["Cache-Control"]
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        token=re.search('name="cra-session" content="([^"]+)"',html)[1]
        body=json.dumps(config()).encode()
        for headers in ({},{"Origin":"https://attacker.invalid","X-CRA-Session":token},{"Origin":base,"X-CRA-Session":"wrong"}):
            with pytest.raises(urllib.error.HTTPError) as error:
                urllib.request.urlopen(urllib.request.Request(base+"/api/configure",body,headers))
            assert error.value.code==403
        request=urllib.request.Request(base+"/api/configure",body,{"Origin":base,"X-CRA-Session":token,"Content-Type":"application/json"})
        result=json.loads(urllib.request.urlopen(request).read())
        assert result["config_hash"]==digest(result["config"])
        request=urllib.request.Request(base,b"",{"Host":"attacker.invalid"},method="GET")
        with pytest.raises(urllib.error.HTTPError):urllib.request.urlopen(request)
        js=urllib.request.urlopen(base+"/app.js").read().decode()
        assert "localStorage" not in js and "innerHTML" not in js and "sessionStorage" not in js
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
