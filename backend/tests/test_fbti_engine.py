from app.services.fbti_engine import match_archetype, score_fbti_code


def test_all_a_is_rldc():
    answers = ["A"] * 8
    assert score_fbti_code(answers) == "RLDC"
    arch = match_archetype("RLDC")
    assert arch["name"] == "持重者"


def test_nearest_archetype():
    arch = match_archetype("SSSS")
    assert arch.get("nearest_archetype") is True
    # 与 SSSS 汉明距离最小的 S 前缀型之一（并列时取字典序最小）
    assert arch["code"] == "SLDA"
