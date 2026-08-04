# quant-sentiment-research — 仓库工作约定（供 Claude Code）

本仓为《Codex 从入门到项目实践》卷四案例仓（A 股舆情量化投研）的可运行配套工程，是书稿代码块的 **source of truth**。

## 项目定位

A 股舆情 + 技术面量化投研 LangGraph Agent，输出研究简报而非买卖指令，用于演示 LangGraph 状态机、 grounding 防幻觉、多模型路由与回测评估。

## 铁律

- **TDD**：每个模块先写失败测试 → 跑确认失败 → 实现 → 跑确认绿 → commit。
- **版本钉死**：依赖与 `version-lock.json` 的 `version_lock` 一致；不引入 lock 外的库。
- **tag 即放行**：全量回归绿后打 `v<MAJOR>.<MINOR>-<NNN>`（NNN=项目号）。
- **只增不改**：扩充时不动现有模块签名/行为；新模块独立测试，CI 双跑。
- **mock-friendly**：`pip install -e ".[dev]" && pytest -q` 必须在无 Key、无 Docker、无网下全绿。

## 技术栈与版本（钉死于 version-lock.json）

- Python 3.10+
- LangGraph 1.2.x
- pandas / pyarrow（最新稳定版）
- pydantic v2
- pytest 8.x

## 验收

```bash
pip install -e ".[dev]"    # 离线可用（首次需联网，之后 node_modules 已就绪）
pytest -q                   # 必须全绿，无需 Key/Docker/网络
```

可选实时行情：`pip install -e ".[live]"`（需 akshare）。

## 目录结构

```text
quant-sentiment-research/
├── pyproject.toml
├── CLAUDE.md
├── version-lock.json
├── src/
│   ├── gateway.py                ← Ch29 金融数据网关
│   ├── sentiment.py              ← Ch30 语义情绪打分
│   ├── graph.py                  ← Ch31 投研状态机
│   ├── nodes.py
│   ├── grounding.py              ← Ch32 证据链防幻觉
│   ├── router.py                 ← Ch33 多模型路由
│   ├── backtest.py               ← Ch34 金标回测
│   └── report.py
└── tests/
```

## 编码约定

- **合规免责**：本仓库不产出任何买卖指令，只做技术研究与教学示例。
- **FakeLLM 驱动**：所有测试用 `FakeLLM`，无需任何 API Key。
- **零伪代码**：禁止 `pass` 占位、`TODO` 占位，每段代码必须可运行。
