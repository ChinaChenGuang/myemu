# KEMU 项目开发计划

## 1. 项目定位与开发原则

`kemu` 是基于 Python 的 Palladium（ICE & IXCOM/SA）编译、仿真与发布脚本编排工具，严格遵循 Cadence WXE 24.05 官方手册语法，核心链路为：

```text
CLI 参数 + database.toml -> Python 解析与严格环境校验 -> Jinja2 渲染 xxx.csh / xxx.qel -> 执行（支持多线程 / 可选 LSF）
```

*(注：Filelist 清洗（`tools/emu_filelist_process`）、`computeFarm.json` 生成（`tools/emu_gen_computefarm`，`[env].bsub = true` 时）与 `clocks.qel` 生成（`tools/emu_gen_clocks`，解析 DE 时钟表格）均拆分为独立专属脚本工具，共用同一份 `database.toml` 配置，保持 `kemu` 本身简洁。)*

**开发原则**：
1. **避免过度开发**：不引入复杂框架、抽象工厂或多余设计模式，直接面向 Palladium ICE & IXCOM 流程编写；配置保持单文件自包含。
2. **简单易懂**：脚本和模板直观可读，工程师能直接看懂生成的 `.csh` / `.qel` 并方便微调。
3. **官方手册强对齐**：所有命令行选项、QEL/XEL 语句与 `computeFarm.json` 结构均以 `/home/chen/proj/Cadence/wxe_doc/` 官方 WXE 24.05 手册为唯一准绳。

---

## 2. 技术选型与运行约束

- **Python 版本**：Python 3.11+（标准库 `tomllib`、`concurrent.futures.ThreadPoolExecutor`、`argparse`）。
- **外部依赖**：仅 `jinja2`。
- **内置默认工具命令**（版本通过 `[env].setup_scripts` 控制，不在 `database.toml` 冗余覆盖）：
  - ICE：`vavlog` / `vavhdl`（analysis）、`vaelab`（elaborate）、`xeCompile`（impt/precomp/comp）、`xeDebug`（sim）。
  - IXCOM（SA）：`vlan` / `vhan`（analysis）、`ixcom`（compile）、`xrun`（sim）。
- **严格环境隔离**：编译与仿真阶段不使用外部 shell 环境变量，路径锚点 `EMU_ROOT` 来自 `[env].emu_root`，其余官方/自定义变量来自 `[env.vars]`；生成的脚本采用 `tcsh`/`csh`（`#!/usr/bin/env tcsh`），开头先按序 `setenv`（`EMU_ROOT` 最先设置，若含 `XE_HOST_FILE` 则先 `unsetenv XE_HOST`）再 `source [env].setup_scripts`，并通过 `$status` 传递退出码。
- **执行模式**：
  - 默认生成 `xxx.csh`（及必要的 `.qel`、`va.lib` / `libmaprc`）并立即通过 `tcsh` 执行。
  - 提供 `--gen-only` 选项：仅渲染脚本，不实际执行，便于检查或手动提交。
- **调度方式**：由 `[env].bsub`（`true`/`false`）与 `[env].queues`、`[env].bsub_opts`、`[env.farm]` 统一控制；`bsub = true` 时，前端与仿真走 `bsub` 提交，`xeCompile` 阶段则使用由 `tools/emu_gen_computefarm` 生成的 `computeFarm.json` 接入集群。

---

## 3. 目录结构规划

```text
KEMU/
├── kemu                        # 可执行入口脚本（chmod +x，可直接 ./kemu 或加入 PATH）
├── pyproject.toml              # 精简项目配置（Python >= 3.11, 仅依赖 jinja2, console_scripts = kemu）
├── GEMINI.md                   # 工作区强约束规则（WXE 24.05 官方手册核验 + tcsh/隔离约定）
├── kemu_src/                   # 核心代码（扁平结构）
│   ├── __init__.py
│   ├── cli.py                  # 命令行入口与参数解析（help / build / sim / release）
│   ├── db_config.py            # 读取与严格校验 database.toml，基于 [env].emu_root 与 [env.vars] 解析路径
│   ├── render.py               # Jinja2 模板加载与渲染，生成可执行 xxx.csh / xxx.qel
│   ├── runner.py               # 脚本执行与日志落盘，支持多线程并发与 bsub 提交
│   ├── build_ice.py            # build ice：analysis / elaborate / syn / impt / precomp / comp
│   ├── build_ixcom.py          # build ixcom：analysis / comp / all
│   ├── sim_ice.py              # sim ice：xeDebug 启动脚本与 run.tcl 生成
│   ├── sim_ixcom.py            # sim ixcom：xrun -R 启动脚本与 run.tcl 生成
│   └── release.py              # release：tar 打包与 DB 时间戳目录发布
├── templates/                  # Jinja2 模板（严格对齐 WXE 24.05）
│   ├── shared/
│   │   ├── _env_header.csh.j2  # 公共 tcsh 环境头部模板（setenv / source / cd）
│   │   ├── _symmetric_config.qel.j2 # 共享 symmetricConfiguration 模板
│   │   ├── clocks.qel.j2       # 共享时钟 QEL 模板（tools/emu_gen_clocks 输出）
│   │   └── trigger.tdf.j2      # 共享 SDL 触发定义模板（[sim.tdf] -> trigger.tdf）
│   ├── ice/
│   │   ├── va.lib.j2           # ICE 库映射文件模板
│   │   ├── analysis_vlog.csh.j2
│   │   ├── analysis_vhdl.csh.j2
│   │   ├── elaborate.csh.j2
│   │   ├── impt.csh.j2
│   │   ├── import.qel.j2
│   │   ├── precomp.csh.j2
│   │   ├── compilerOptions.qel.j2
│   │   ├── precompileOptions.qel.j2
│   │   ├── keepNets.qel.j2
│   │   ├── precompile.qel.j2
│   │   ├── comp.csh.j2
│   │   ├── compile.qel.j2
│   │   ├── sim.csh.j2
│   │   ├── run.tcl.j2
│   │   ├── gen_fsdb_offline.tcl.j2
│   │   └── sb/                 # SpeedBridge 子模板
│   └── ixcom/
│       ├── libmaprc.j2         # IXCOM 库映射文件模板
│       ├── analysis_vlan.csh.j2
│       ├── analysis_vhan.csh.j2
│       ├── gen_clk.csh.j2
│       ├── ixcom_build.csh.j2  # 单次编译模板（ixcom）
│       ├── import.qel.j2
│       ├── compile.qel.j2
│       ├── sim.csh.j2
│       └── run.tcl.j2
├── tools/                      # 解耦的独立专属脚本工具（共用 database.toml）
│   ├── prep_flists.csh.j2      # Filelist 清洗脚本模板
│   ├── emu_filelist_process    # 独立 filelist 清洗脚本
│   ├── emu_gen_computefarm     # 独立 computeFarm.json 生成脚本
│   └── emu_gen_clocks          # 解析 DE 时钟表格生成 clocks.qel
├── examples/
│   ├── ice_database.toml       # ICE 单文件一站式示例配置（遵循 TOML_SPEC.md）
│   ├── ice_netlist.toml        # ICE 双文件解耦前端 Netlist 示例
│   ├── ice_db_fv.toml          # ICE 双文件解耦后端 Database 示例
│   └── ixcom_database.toml     # IXCOM (SA) 日常单文件示例配置（遵循 TOML_SPEC.md）
└── tests/                      # 单元测试（不依赖真实 Palladium 环境即可运行）
```

---

## 4. 命令与功能规划

### 4.1 `kemu help`
- 输出各子命令（`build` / `sim` / `release`）的用法说明与典型使用示例。

### 4.2 `kemu build`
- `kemu build ice --db <db_name> --comdir <path> --act <action> [--gen-only]`
  - **`--db` 解析规则**：传入 `<db_name>` 时无需加 `.toml` 后缀，工具自动补全 `.toml`（若已显式传入 `*.toml` 亦可直接识别）。
  - **统一 `--comdir` 与前后端目录解耦**：`--comdir` 绝对路径直接使用 `<path>`，相对路径以 `[env].emu_root` 为基准拼为 `$EMU_ROOT/<path>`（不引入 `--netlist-dir`）：
    - **前端目录 `<comdir>/netlist/<netlist.name>/`**：`analysis`、`elaborate`、`syn` 的工作目录（产出 `va.lib`、`*.vg` 及产物清单 `netlist_manifest.toml`）。
    - **后端目录 `<comdir>/database/<database.name>/`**：`impt`、`precomp`、`comp` 的工作目录（按 `[database].netlist` 定位 `<comdir>/netlist/<netlist>/netlist_manifest.toml` 直接引用 `.vg`，不拷贝网表；单文件同时写 `[netlist]` 与 `[database]` 时自动继承 `[netlist].name`）。
  - **`--act` 支持的动作**：
    - `analysis`：生成 `va.lib`，按 `[[analysis.module]]` 并发生成并执行 `analysis_<name>_vlog.csh`（`vavlog -logFile ...`）与 `analysis_<name>_vhdl.csh`（`vavhdl -logFile ... -file ...`）。
    - `elaborate`：并发渲染并执行 `design_top` 与 `testbench_top` 两路 `vaelab <top> -logFile ... -outputVlog ...` 脚本，并写出 `netlist_manifest.toml`。
    - `syn`：顺序执行 `analysis` -> `elaborate`。
    - `impt`：读取 `netlist_manifest.toml`（或 `[impt].netlist_files`），渲染 `import.qel` 与 `impt.csh`，执行 `xeCompile [-z2|-z3] -log impt.log import.qel`（`bsub = true` 时 `designImport -useLSF` 并依赖 `computeFarm.json`）。
    - `precomp`：结合 `[comp].compiler_options`/`flow`（确保 `compilerOptions.qel` 在 `precompile` 之前执行）与 `[precomp]`（`precompileOptions.qel`、`keepNets.qel`、可选 `clocks_qel`、`moduleStub`/`instanceStub` DB 裁剪）渲染 `precompile.qel` 与 `precomp.csh`，执行预编译检查。
    - `comp`：按 `flow`（`unified` / `ppc`）与 `[emulator]`/`[comp]` 渲染 `compilerOptions.qel`、`compile.qel`（含 `target_compile_scripts`、`icePrepare`）与 `comp.csh`，执行最终编译。
- `kemu build ixcom --db <db_name> --comdir <path> --act <analysis|comp|all> [--gen-only]`
  - IXCOM 日常采用单文件配置（不写 `[netlist]`），全程直接在 `<comdir>/database/<database.name>/` 生成 `libmap.rc`、按需生成时钟后执行 `vlan`/`vhan` 与单次 `ixcom` 编译脚本。（若显式配置 `[netlist]` + `[database].netlist`，则 `analysis` 落在 `<comdir>/netlist/<netlist.name>/`，后端通过 `-libmaprc` 复用。）

### 4.3 `kemu sim`
- `kemu sim ice   --db <db_name> --db-path <path> --simdir <path> --session <session_name> [--gen-only]`
  - 按 `[sim]` / `[sim.wave]` / `[sim.tdf]` 与 `[emulator]` 激活机器渲染 `trigger.tdf`（可选，`[sim.wave].enable = true` 时自动插入 `sdl -setFile/-load/-enable`）、`run.tcl`（`debug <db_path> -session <session>` -> `host <emu_host> -path [pwd]` -> `download` -> 可选 `configPM` / `target_run_scripts` / `[sim.wave]` + `[sim.tdf]` / `tcl_file` / `run_cmd` / 收尾）与 `sim.csh`（`xeDebug -host ... -session ... -log sim.log -init run.tcl`）。
- `kemu sim ixcom --db <db_name> --db-path <path> --simdir <path> --session <session_name> [--gen-only]`
  - 使用同一套 `[sim]` / `[sim.wave]` / `[sim.tdf]` 上下文渲染 `trigger.tdf`、`run.tcl` 与 `sim.csh`（由 `[emulator]` 激活机器注入 `XE_HOST` / `XE_HOST_FILE`，可选 `DBE_HOST` 由 `[env.vars]` 配置，并执行 `xrun -R -xmlibdirname <db_path> -input run.tcl`）。

### 4.4 `kemu release`
- `kemu release --db <db_name> --comdir <path> --type <tar|DB>`
  - 从 `<comdir>/database/<database.name>/` 收集 `[release].include`：
  - `--type tar`：打包为 `<dest_dir>/<db_prefix>_<name>_<yymmddhhmm>.tar.gz`。
  - `--type DB`：拷贝到单层时间戳目录 `<dest_dir>/<db_prefix>_<name>_<yymmddhhmm>/`。

---

## 5. 分阶段开发与验证里程碑

| 阶段 | 任务 | 验证方式 |
|---|---|---|
| **M1** | 搭建项目骨架、`cli.py`（`help` / `build` / `sim` / `release`，支持 `--db <db_name>` 自动补齐 `.toml`）与 `db_config.py`（严格字段校验、`[netlist]`/`[database]` 按需校验、`[emulator]` 机器池与 `[env.vars]` 隔离解析） | 运行 `kemu help`、测试 `TOML_SPEC.md` 全部校验规则 |
| **M2** | 实现 `render.py`（Jinja2 渲染、`StrictUndefined`）与 `runner.py`（`tcsh` 执行、`bsub` 拼接、日志落盘、多线程调度） | 单元测试并发执行、LSF 命令拼接、失败捕获与 `--gen-only` 模式 |
| **M3** | 实现 `build_ice.py` 与 `build_ixcom.py`（ICE 前后端 `<comdir>/netlist/<name>/` 与 `<comdir>/database/<name>/` 解耦 + `netlist_manifest.toml` 交接，IXCOM 单文件与可选复用流程） | 在临时 `EMU_ROOT` 下验证 ICE 6 个 `--act`（含 1 对 N 解耦）与 IXCOM 渲染执行 |
| **M4** | 实现 `sim_ice.py` 与 `sim_ixcom.py`（`--db-path`/`--simdir`/`--session`、`[emulator]`/`DBE_HOST` 注入与 `[sim]`/`[sim.wave]`/`[sim.tdf]` 统一渲染） | 验证多编译目录切换仿真、日志归集与 `trigger.tdf` / `run.tcl` 生成 |
| **M5** | 实现 `release.py`（`tar` 与 `DB` 单层时间戳目录） | 验证 tar 包内容完整性、DB 目录命名与缺失文件校验 |
| **M6** | 编写完整单元测试 `tests/`、维护 4 份 `examples/` 示例配置与精简 `README.md` | 运行 `pytest` / `unittest` 全量通过 |
| **M7** | 实现 `tools/` 下的三个独立专属脚本工具（`tools/emu_filelist_process`、`tools/emu_gen_computefarm`、`tools/emu_gen_clocks`）及单元测试 | 在临时 `EMU_ROOT` 下验证 filelist 清洗、`computeFarm.json` 及 `clocks.qel` 生成结果 |

---

## 6. 后续实现阶段待迭代项

1. **`trigger.tdf` 模板与 `[sim.tdf]` 配置精简（关联 M4）**
   - 当前 `[sim.tdf]` 与 [trigger.tdf.j2](file:///home/chen/proj/KEMU/templates/shared/trigger.tdf.j2) 引入了较多高级选项（`enable1`/`enable2`、`counter1`/`counter2`、`aliases`、`acquire`/`no_acquire` 等），存在过度设计风险。
   - 后续在 **M4（`sim_ice.py` / `sim_ixcom.py`）** 实现时，对照 `SDL.pdf` P217–P218 官方语法（如 `scope <scope>;`、`Instance <inst>;`、`State <state> { if (<expr>) { <TRIGGER_NAME>: trigger; } }`），按最常用触发场景进一步精简模板结构与 TOML 字段。
2. **模板上下文变量命名规范统一（关联 M2 / M3 / M4）**
   - 当前 `templates/` 下尚未与 Python 渲染代码联调，模板间上下文命名尚不统一（如部分模板使用扁平字段 `db_name`/`emu_host`/`et3confg`，部分使用嵌套对象 `cfg.file`/`wave.xxx`/`tdf.xxx`，以及 `templates/ice/sb/*.j2` 历史变量残留）。
   - 在 **M2（`render.py`）**、**M3（`build_*.py`）** 与 **M4（`sim_*.py`）** 编码实现过程中，同步制定统一的 Jinja2 上下文命名契约并逐个审计重构所有 `.j2` 模板，确保全量模板在 `StrictUndefined` 单元测试下命名一致、零残留。
3. **IXCOM 分阶段 `-target`（`swmodel` / `hdlice` / `xecompile`）编译流（延后迭代）**
   - 当前版本先聚焦已验证跑通的 `analysis`（`libmap.rc` + `ixclkgen` + `vlan`/`vhan`）与单次 `comp`（`ixcom`）及 `all`，暂不拆 `-target` 分阶段流程，待后续梳理清楚后再按需迭代扩展。
4. **不可综合模块裁剪统一抽象（`wipe_module`）与时钟表联动（关联 M3 / M7）**
   - 依据 `compileICE.pdf` P55/P57 与 `compileIXCOM.pdf` P46–P48，后续统一维护不可综合/模拟模块裁剪名单（ICE 在 `vavlog` 中渲染为 `+ModuleStub+<m1>+<m2>`，IXCOM 在 `ixcom` 中渲染为 `-bbcell <m>`）。
   - 时钟统一由 `tools/` 解析设计时钟表格产出 `clocks.qel`：ICE `precomp` 直接 `source clocks.qel`，IXCOM 通过 `ixclkgen -input clocks.qel` 消费并生成时钟模块。

*(详细 TOML 配置规范见 [TOML_SPEC.md](./TOML_SPEC.md))*
