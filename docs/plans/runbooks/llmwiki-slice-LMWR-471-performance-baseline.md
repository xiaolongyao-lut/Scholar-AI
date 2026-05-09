# LLM-Wiki 集成切片 Runbook

> LMWR-471 · Wiki performance baseline P50/P95/P99

---

## 切片标识

| 字段 | 值 |
| ---- | ---- |
| 任务 ID | LMWR-471 |
| 简短描述 | 扩展 Wiki zero-cost performance baseline，记录 compile/index/query/doctor latency P50/P95/P99 与吞吐量。 |
| Wave | Wave 15 supplement |
| 执行者 | Codex |
| 完成时间 | 2026-05-04T22:15:00+08:00 |

---

## 1. 回档点

| 字段 | 值 |
| ---- | ---- |
| checkpoint | `C:\Users\xiao\.codex\rollback-checkpoints\Modular-Pipeline-Script-89acfed628ba0f54\20260504-220215-llmwiki-lmwr471-performance-baseline` |

恢复只在用户明确要求时执行：

```powershell
py "$env:USERPROFILE\.codex\skills\longrun-autopilot\scripts\checkpoint.py" restore --workspace "C:\Users\xiao\Desktop\tools\Modular-Pipeline-Script" --checkpoint "20260504-220215-llmwiki-lmwr471-performance-baseline" --confirm-restore
```

---

## 2. 成熟方案研究

| 参考来源 | 路径 / 链接 | 借鉴点 |
| ---- | ---- | ---- |
| Python `time.perf_counter()` | `https://docs.python.org/3/library/time.html#time.perf_counter` | 使用单调高精度计时，不受系统时钟调整影响。 |
| Python `timeit` docs | `https://docs.python.org/3/library/timeit.html` | 多轮样本比单次样本更稳定；当前脚本用 isolated temp-workspace iterations。 |
| Python `statistics` docs | `https://docs.python.org/3/library/statistics.html` | 输出 mean 与 percentile summary，避免只看单次 timing。 |
| 本地 Wave 14 runbook | `docs/plans/runbooks/llmwiki-slice-LMWR-441-443-447-448-wave14-final-gate.md` | 保留 zero-cost/temp workspace/no runtime artifact 边界，并扩展 doctor。 |

---

## 3. 核心代码

| 文件 | 覆盖 |
| ---- | ---- |
| `tools/eval/wiki_wave14_performance_baseline.py` | 新增 `BaselineSample`、多轮 iterations、compile/index/query/doctor/total latency summary、P50/P95/P99、throughput_per_second、CLI `--iterations`。 |
| `tests/wiki/test_performance_baseline.py` | 覆盖 schema v2、percentiles、throughput、invalid iterations guard。 |

---

## 4. Baseline Result

命令：

```powershell
& .\.venv-1\Scripts\python.exe tools\eval\wiki_wave14_performance_baseline.py --iterations 5 --pretty
```

结果摘要：

| 指标 | P50 ms | P95 ms | P99 ms |
| ---- | ------ | ------ | ------ |
| compile | 4.979 | 6.073 | 6.073 |
| index | 10.562 | 11.334 | 11.334 |
| query | 0.204 | 0.235 | 0.235 |
| doctor | 5.558 | 6.124 | 6.124 |
| total | 32.147 | 33.74 | 33.74 |

吞吐量摘要：

| 指标 | value/sec |
| ---- | --------- |
| compile_pages | 387.222 |
| queries | 4793.864 |
| doctor_checks | 1067.464 |

边界：

- `schema_version=2`
- `iterations=5`
- `mode=zero_cost_temp_workspace`
- `error_count=0`
- 不调用模型，不改 qrels/goldset，不写 runtime artifacts。

---

## 5. Verification

```powershell
& .\.venv-1\Scripts\python.exe -m compileall -q tools\eval\wiki_wave14_performance_baseline.py tests\wiki\test_performance_baseline.py
& .\.venv-1\Scripts\python.exe -m pytest tests\wiki\test_performance_baseline.py -q
& .\.venv-1\Scripts\python.exe tools\eval\wiki_wave14_performance_baseline.py --iterations 5 --pretty
```

| 检查项 | 结果 |
| ------ | ---- |
| compileall | PASS |
| performance baseline focused pytest | PASS（2 passed） |
| baseline CLI smoke | PASS（5 iterations, schema v2, P50/P95/P99 present） |

---

## 6. Open / 后续

- 当前基线是临时工作区 micro-baseline，不代表真实用户大型库性能。
- 若后续做真实 runtime baseline，必须先确认数据集、隐私、输出路径和 no-secret scan。
- LMWR-472 Wiki security audit 与 LMWR-473 observability 仍未完成。
