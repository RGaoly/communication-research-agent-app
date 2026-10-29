"""Versioned target rules. Only explicit official rules create format blockers."""
import re


def check_profile(profile, text):
    issues = []
    for source in profile.get("sources", []):
        for rule in source.get("requirements", []):
            severity = "blocking" if source["kind"] == "official" else "warning"
            code, value = rule.get("code"), rule.get("value")
            mismatch = False
            measured = None
            if rule.get("scope", "all") != "all":
                issues.append({"code": "manual_target_scope", "severity": "warning", "location": "target_profile", "evidence": "Publisher-specific counting scope is not automatically parsed", "resolution": "Check rendered final text against official counting exclusions", "source": source["url"]})
                continue
            if code == "max_words" and type(value) is int and value > 0:
                measured = len(text.split())
                mismatch = measured > value
            elif code == "max_nonspace_characters" and type(value) is int and value > 0:
                measured = len(re.sub(r"\s", "", text))
                mismatch = measured > value
            elif code == "required_sections" and isinstance(value, list):
                measured = [section for section in value if not re.search(r"(?m)^## " + re.escape(section) + r"\s*$", text)]
                mismatch = bool(measured)
            elif code == "anonymous" and value is True:
                measured = bool(re.search(r"(?im)^(?:作者|author|affiliation|单位)\s*[:：]", text))
                mismatch = measured
            else:
                issues.append({"code": "manual_target_check", "severity": "warning", "location": "target_profile", "evidence": "Target rule needs manual verification: " + str(code), "resolution": "Verify current official requirement and rendered final document", "source": source["url"]})
                continue
            if mismatch:
                issues.append({"code": "target_rule_" + code, "severity": severity, "location": "draft", "evidence": "Declared target rule not met; measured=" + str(measured), "resolution": "Revise document or correct rule/source classification with human approval", "source": source["url"]})
    return issues
