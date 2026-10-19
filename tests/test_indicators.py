"""指标计算测试：MA / RSI / MACD / 技术面合成分。"""

from quant_sentiment.indicators import ma, macd, rsi, technical_score


def test_ma_basic():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ma(closes, 3)
    assert result[0] is None
    assert result[1] is None
    assert result[2] == 2.0
    assert result[4] == 4.0


def test_ma_window_larger_than_data():
    result = ma([1.0, 2.0], 5)
    assert result == [None, None]


def test_rsi_all_up_near_100():
    closes = [float(i) for i in range(1, 25)]  # 连续上涨
    value = rsi(closes, 14)
    assert value is not None
    assert value > 95


def test_rsi_insufficient_data_returns_none():
    assert rsi([1.0, 2.0, 3.0], 14) is None


def test_rsi_bounded():
    closes = [10, 11, 10.5, 12, 11.8, 10.2, 13, 12.5, 11, 14, 13.5, 12,
              15, 14, 13, 16, 15, 14.5, 17, 16.5]
    value = rsi(closes, 14)
    assert value is not None
    assert 0.0 <= value <= 100.0


def test_macd_constant_series_is_zero():
    closes = [10.0] * 40
    result = macd(closes)
    assert abs(result["dif"][-1]) < 1e-9
    assert abs(result["dea"][-1]) < 1e-9
    assert abs(result["hist"][-1]) < 1e-9


def test_macd_lengths_match_input():
    closes = [10 + i * 0.1 for i in range(40)]
    result = macd(closes)
    assert len(result["dif"]) == 40
    assert len(result["dea"]) == 40
    assert len(result["hist"]) == 40


def test_technical_score_uptrend_positive():
    closes = [10.0 + i * 0.2 for i in range(60)]  # 稳步上行
    assert technical_score(closes) > 0.3


def test_technical_score_downtrend_negative():
    closes = [20.0 - i * 0.2 for i in range(60)]  # 持续下行
    assert technical_score(closes) < -0.3


def test_technical_score_bounded():
    closes = [10.0 + i * 0.2 for i in range(60)]
    score = technical_score(closes)
    assert -1.0 <= score <= 1.0


def test_technical_score_short_series_uses_trend_only():
    # 数据不足 MA20 时仍可给出趋势方向的分数
    assert technical_score([10.0, 11.0, 12.0]) > 0
    assert technical_score([12.0, 11.0, 10.0]) < 0
