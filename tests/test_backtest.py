import pandas as pd
from quant_sentiment.backtest import run_backtest, BacktestResult
from quant_sentiment.gateway import set_offline


def _momentum(prior_closes):
    return 1 if len(prior_closes) >= 2 and prior_closes[-1] > prior_closes[-2] else 0


def test_run_backtest(tmp_path):
    pd.DataFrame({"date": ["2026-01-0%d" % i for i in range(1, 6)],
                  "close": [10.0, 10.5, 10.2, 10.8, 11.0]}).to_parquet(tmp_path / "kline_600000.parquet")
    set_offline(True)
    res = run_backtest(_momentum, "600000", str(tmp_path))
    assert isinstance(res, BacktestResult)
    assert 0.0 <= res.precision <= 1.0
    assert 0.0 <= res.recall <= 1.0
    assert res.samples > 0
