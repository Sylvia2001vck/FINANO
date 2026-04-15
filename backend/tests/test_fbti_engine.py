from app.services.fbti_engine import match_archetype, score_fbti_code


def test_all_a_is_rldc():
    answers = ["A"] * 8
    assert score_fbti_code(answers) == "RLDC"
    arch = match_archetype("RLDC")
    assert arch["name"] == "守财金牛"


def test_nearest_archetype():
    arch = match_archetype("SSSS")
    assert arch.get("nearest_archetype") is True
