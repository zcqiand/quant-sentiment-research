from quant_sentiment.router import route_model


def test_simple_routes_lite():
    assert route_model("simple") == "lite"


def test_hard_routes_flagship():
    assert route_model("hard") == "flagship"


def test_unknown_routes_mock():
    assert route_model("unknown") == "mock"
