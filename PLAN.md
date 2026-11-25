# KEMU 项目开发计划

## 1. 项目定位与开发原则

`kemu` 是基于 Python 的 Palladium（ICE）编译、仿真与发布脚本编排工具，核心链路为：

```text
CLI 参数 + database.toml -> Python 解析 & Filelist 预处理 -> Jinja2 渲染 xxx.sh / xxx.qel -> 执行（支持多线程 / 可选 LSF）
```

**开发原则**：
1. **避免过度开发**：不引入复杂框架、抽象工厂或多余设计模式，直接面向 Palladium 流程编写；配置保持单文件自包含。
2. **简单易懂**：脚本和模板直观可读，工程师能直接看懂生成的 `.sh` / `.qel` 并方便微调。
3. **命名贴合实际项目**：模块、函数和配置字段均使用 Palladium / Emulation 真实术语（`ice`、`analysis`、`elaborate`、`syn`、`impt`、`precomp`、`comp`、`sim`、`release`、`comdir`、`simdir`、`session`）。

---

## 2. 技术选型与运行约束

- **Python 版本**：Python 3.11+（使用标准库 `tomllib` 解析 TOML，使用 `concurrent.futures.ThreadPoolExecutor` 实现多线程调度，使用 `argparse` 解析命令行）。
- **外部依赖**：仅 `jinja2`。
- **内置默认工具命令**：`vavlog`（analysis）、`vaelab`（elaborate）、`xeCompile`（impt/precomp/comp）、`xeDebug`（sim），均可在 `database.toml` 中按需覆盖。
- **执行模式**：
  - 默认生成 `xxx.sh`（及必要的 `.qel`、处理后的 filelist）并立即执行。
  - 提供 `--gen-only` 选项：仅渲染脚本与 filelist，不实际执行，便于检查或手动提交。
- **调度方式**：默认本地 `bash xxx.sh` 执行；支持在 `database.toml` 中全局或按阶段配置集群提交前缀（如 `bsub ...`）。

---

## 3. 目录结构规划

```text
KEMU/
├── kemu                     # 可执行入口脚本（chmod +x，可直接 ./kemu 或加入 PATH）
├── pyproject.toml           # 精简项目配置（Python >= 3.11, 仅依赖 jinja2, console_scripts = kemu）
├── kemu_src/                # 核心代码（扁平结构）
│   ├── __init__.py
│   ├── cli.py               # 命令行入口与参数解析（help / build / sim / release）
│   ├── db_config.py         # 读取与校验 database.toml，解析 $EMU_ROOT 路径
│   ├── filelist.py          # Filelist 预处理（先 delete 后 replace，输出到编译目录）
│   ├── render.py            # Jinja2 模板加载与渲染，生成可执行 xxx.sh / xxx.qel
│   ├── runner.py            # 脚本执行与日志落盘，支持多线程并发（analysis 阶段）与可选 bsub 前缀
│   ├── build_ice.py         # build ice：analysis / elaborate / syn / impt / precomp / comp
│   ├── sim_ice.py           # sim ice：仿真脚本生成、session 绑定与日志归集
│   └── release.py           # release：tar 打包与 DB 时间戳目录发布
├── templates/               # Jinja2 脚本模板
│   ├── ice_analysis.sh.j2   # analysis 脚本模板（默认 vavlog）
│   ├── ice_elaborate.sh.j2  # elaborate 脚本模板（默认 vaelab）
│   ├── ice_impt.sh.j2       # impt 启动脚本（默认 xeCompile import.qel）
│   ├── import.qel.j2        # import.qel 模板
│   ├── ice_precomp.sh.j2    # precomp 启动脚本（默认 xeCompile precompile.qel）
│   ├── precompile.qel.j2    # precompile.qel 模板
│   ├── ice_comp.sh.j2       # comp 启动脚本（默认 xeCompile compile.qel）
│   ├── compile.qel.j2       # compile.qel 模板（支持根据 precomp 结果调整参数）
│   └── ice_sim.sh.j2        # sim ice 启动脚本（默认 xeDebug）
├── examples/
│   └── database.toml        # 完整示例配置（含中文注释，遵循 TOML_SPEC.md）
└── tests/                   # 单元测试（不依赖真实 Palladium 环境即可运行）
```

---

## 4. 命令与功能规划

### 4.1 `kemu help`
- 输出各子命令（`build` / `sim` / `release`）的用法说明与典型使用示例。

### 4.2 `kemu build`
- `kemu build ice --db <database.toml> --comdir <path> --act <action> [--gen-only]`
  - **工作目录**：`$EMU_ROOT/<path>/database/`（若目录不存在则自动创建；若未设置 `$EMU_ROOT` 给出清晰报错）。
  - **所有生成的处理后 filelist、脚本、`.qel`、log 与 database 文件均落在该工作目录下执行与保存**。
  - **`--act` 支持的动作**：
    - `analysis`：
      - 对原始（已展平）filelist 执行 `filelist_delete`（先删）+ `filelist_replace`（后替），输出到当前编译目录。
      - 若未配置 `[[analysis.jobs]]`，使用 `[database].verilog_filelist` 跑单个默认 `vavlog` 任务；
      - 若配置了 `[[analysis.jobs]]`，使用 Python 多线程并发执行各 subsys 的 `vavlog` 任务（每个 job 支持各自的处理规则）。
    - `elaborate`：渲染并执行 `vaelab` 脚本，完成网表创建。
    - `syn`：顺序执行 `analysis` -> `elaborate`（任一步失败即中止）。
    - `impt`：渲染 `import.qel` 与 `impt.sh`，执行 `xeCompile import.qel`。
    - `precomp`：渲染 `precompile.qel` 与 `precomp.sh`，执行 `xeCompile precompile.qel`。
    - `comp`：渲染 `compile.qel` 与 `comp.sh`，支持 `[comp.params]` + `qel_lines` 灵活调整参数，执行最终 database 编译。
- `kemu build ixcom ...`
  - 明确输出提示：`ixcom 暂不支持` 并返回非零退出码。

### 4.3 `kemu sim`
- `kemu sim ice --db <database.toml> --simdir <path> --session <session_name> [--gen-only]`
  - `--simdir`：仿真日志归集目录（不存在则自动创建）。
  - `--session`：指定 Palladium 仿真 session 名称，传入模板渲染到 `sim.sh`。
- `kemu sim ixcom ...`
  - 明确输出提示：`ixcom 暂不支持` 并返回非零退出码。

### 4.4 `kemu release`
- `kemu release --db <database.toml> --comdir <path> --type <tar|DB>`
  - 根据 `[release]` 配置的必要目录/文件/脚本清单，从 `$EMU_ROOT/<comdir>/database/` 收集目标内容。
  - `--type tar`：打包为 `<dest_dir>/<db_prefix>_<name>_<yymmddhhmm>.tar.gz`。
  - `--type DB`：拷贝到单层时间戳目录 `<dest_dir>/<db_prefix>_<name>_<yymmddhhmm>/`（如 `database_min_system_2607111221/`）。

---

## 5. 分阶段开发与验证里程碑

| 阶段 | 任务 | 验证方式 |
|---|---|---|
| **M1** | 搭建项目骨架、`cli.py`（`help` / `build` / `sim` / `release` + `ixcom` 拦截）与 `db_config.py` | 运行 `kemu help`、测试 `TOML_SPEC.md` 配置解析与按需校验 |
| **M2** | 实现 `filelist.py`（先 delete 后 replace 落地编译目录）、`render.py`（Jinja2 渲染）与 `runner.py`（执行、LSF 覆盖、日志落盘、多线程调度） | 单元测试 filelist 预处理、并发执行、失败捕获与 `--gen-only` 模式 |
| **M3** | 实现 `build_ice.py` 与 `analysis/elaborate/syn/impt/precomp/comp` 模板 | 在临时 `$EMU_ROOT` 下跑通全部 6 个 `--act` 动作（含单 filelist 与多 job 两种 analysis 模式） |
| **M4** | 实现 `sim_ice.py` 与 `ice_sim.sh.j2` 模板 | 验证 `--simdir` 日志归集、`--session` 注入与脚本生成 |
| **M5** | 实现 `release.py`（`tar` 与 `DB` 单层时间戳目录） | 验证 tar 包内容完整性、DB 目录命名与缺失文件校验 |
| **M6** | 编写完整单元测试 `tests/`、示例 `examples/database.toml` 与精简 `README.md` | 运行 `pytest` / `unittest` 全量通过 |

*(详细 TOML 配置规范见 [TOML_SPEC.md](./TOML_SPEC.md))*
