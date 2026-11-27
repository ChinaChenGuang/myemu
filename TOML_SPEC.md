# KEMU `database.toml` 配置文件规范（WXE 24.05）

本文档定义 `kemu` 所使用的 `database.toml` 配置文件结构、Section 职责边界、书写风格规范、字段定义、环境变量规则与校验约束。所有工具参数、XEL/QEL 语法与 `computeFarm.json` 结构均严格对照 Cadence Palladium Z2/Z3（WXE 24.05）官方手册（`compileICE.pdf`、`compileIXCOM.pdf`、`emulator.pdf`、`DebuggingDesigns.pdf`、`xecmdref.pdf`）。

---

## 1. 设计约定与边界划分

1. **扁平直观、职责单一**：按 Palladium ICE 与 IXCOM（SA）实际工程阶段划分 Section，每个 Section 边界明确、互不重叠：

| Section | 职责定位 | 包含内容 | 不包含内容 |
|---|---|---|---|
| `[netlist]` | 前端网表元信息（ICE 主用；IXCOM 日常单文件可省略） | `name`、`design_top`、`testbench_top`、`platform`、`desc` | 后端数据库名、板卡分配、硬件 host |
| `[database]` | 后端 Database 元信息 | `name`、`netlist`、`netlist_dir`、`design_lib`、`desc`（IXCOM 日常单文件或导入裸 `.vg` 时可含 `design_top`/`testbench_top`） | 路径规则、工具参数、硬件机器池、阶段配置 |
| `[env]` / `[env.vars]` / `[env.farm]` | 运行环境与集群调度 | `emu_root`、`setup_scripts`、`bsub`、`queues`、`bsub_opts`、可选官方/项目环境变量表 `[env.vars]` 与 `[env.farm]` | 硬件机器配置（见 `[emulator]`）、某一编译/仿真阶段的专属工具选项 |
| `[emulator]` / `[emulator.machines]` | Palladium 硬件机器池与激活目标 | `active`、`target_system`、`[emulator.machines]` 机器映射表（每台机器含 `host`、`et3confg`、可选 `target_system`） | 集群 LSF 调度、环境变量、板卡/域分配（`boards` 见 `[comp]`） |
| `[filelist]` | 源码清洗规则 | `delete`、`replace` 规则（供 `tools/emu_filelist_process` 读取同一份配置消费） | filelist 路径清单（不与 `[[analysis.module]]` 重复定义） |
| `[analysis]` / `[[analysis.module]]` | 按模块粒度的 RTL/TB 分析 | 并发数、公共编译选项、`module` 列表及其源码清单与模块级选项（ICE 生成 `va.lib`，IXCOM 生成 `libmaprc`） | `elaborate` 或后端编译参数 |
| `[elaborate]` | ICE 顶层并行展开建网表 | `design_top` 与 `testbench_top` 并行 `vaelab` 的选项与 `extra_lines` | filelist 清单、IXCOM 参数 |
| `[impt]` / `[precomp]` / `[comp]` | ICE 后端导入、预检查与编译 | 各阶段 `xeCompile` 选项、导入模式、`precompile_options` / `keep_nets` / `clocks_qel` / `module_stubs` / `instance_stubs`、编译流 `flow`、`compiler_options`、`target_compile_scripts`、`boards` 与 `symmetric_boards` / `[[comp.symmetric]]` | 已在 `[netlist]` / `[database]` / `[emulator]` 定义的顶层名、硬件机器池、阶段 `bsub_opts` |
| `[ixcom]` | IXCOM（SA）编译配置 | 单步/多步模式、`vlan`/`vhan`/`ixcom` 参数、分阶段 `-target` 控制、自定义 QEL 开关 | 已在 `[database]` / `[netlist]` / `[emulator]` / `[analysis]` 定义的顶层、硬件主机与源码清单 |
| `[sim]` / `[sim.wave]` / `[sim.tdf]` | 运行期仿真、波形与触发配置 | ICE（`xeDebug`）与 IXCOM（`xrun -R`）的 `tcl_file`、`pm_mode`、`target_run_scripts`、`run_cmd`、`auto_exit`、runtime Hooks、`[sim.wave]`、`[sim.tdf]`、启动 `opts` 与 `extra_lines`（`--db-path` / `--simdir` / `--session` 由 CLI 传入） | 硬件 host（直接复用 `[emulator]` 激活机器的 `host` / `et3confg`） |
| `[release]` | 交付打包规则 | `dest_dir`、`db_prefix`、`include`、`exclude` | 编译/仿真运行参数 |

2. **模式 C（同 Schema 兼容单文件一站式与 ICE 前后端解耦）与三层界限**：
   - 同一套配置 Schema 通过“按需校验 + 产物清单 `netlist_manifest.toml`”同时支持两种工程组织形式（**不引入多文件 TOML 继承/合并机制**）：
     - **单文件一站式**：在同一份配置中同时包含 `[netlist]` 与 `[database]`（或 IXCOM 日常单文件仅写 `[database]`），一次维护、按 `--act` 分阶段执行。
     - **ICE 双文件解耦（1 个 Netlist 复用 N 个 Database）**：前端独立编写 `netlist.toml`（含 `[netlist]`/`[filelist]`/`[analysis]`/`[elaborate]`），`elaborate` 完成后自动在网表目录写出产物契约 `netlist_manifest.toml`；后端各 `database_*.toml` 省略前端段，仅通过 `[database].netlist` 指向对应 netlist 名称即可直接引用 `.vg` 建库（不拷贝网表大文件）。
     - **IXCOM 日常单文件**：IXCOM（SA）无独立 `.vg` 网表交接步骤，日常直接维护单份配置文件，无需编写 `[netlist]`（在 `[database]` 中填写 `design_top`/`testbench_top`）。
   - **第 1 层（收进模板与内置默认值）**：工具固定套路与团队基线（如 `vavlog -sv -db2`、`vavhdl -V2008`、`vaelab -keepAllFlipFlop`、`importOption {mode full}`、`refLib qtref generic`、`compilerOption {mode ice}` / `{visionMode FV}`、`xeDebug -noecho`、`[env.farm]` 默认资源模板）直接由模板和默认值提供，**日常配置无需书写**。
   - **第 2 层（留在日常 TOML）**：随 netlist/database 或项目变化的核心参数（`[netlist]`、`[database]`、`[env]`、`[emulator]`、`[filelist]`、`[[analysis.module]]`、`clocks_qel`、`keep_nets`、`[comp].boards`、`[sim].tcl_file`、`[release]`）。
   - **第 3 层（按需覆写与逃生舱）**：所有默认值空项（`[]` / `''`）及与默认值一致的整段（如纯 ICE 下的 `[impt]`、`[elaborate]`、`[ixcom]`）**均可省略**；仅在需要偏离默认值时才填写。
3. **严格环境隔离（不读取外部环境变量）**：
   - `kemu` 编译与仿真**不使用外部 shell 中的环境变量**，Python 侧解析路径与渲染脚本时**绝不读取 `os.environ`**。
   - `[env].emu_root` 与可选 `[env.vars]` 显式定义运行时所需全部环境变量；`[env.vars]` 优先直接使用 Cadence WXE 24.05 官方环境变量（`GenericSettingUp_PD.pdf` P32–P55、`xecmdref.pdf` P203–P204, P354, P945），既减少重复封装配置，又避免不同平台/宿主机残留环境变量造成冲突。
   - 生成的 `.csh` 脚本采用 `#!/usr/bin/env tcsh`，开头先设置 `setenv EMU_ROOT '<emu_root>'`（若 `[env.vars]` 含 `XE_HOST_FILE` 则先执行 `unsetenv XE_HOST`，见 `emulator.pdf` P16），再按序 `setenv` `[env.vars]`，接着依次 `source [env].setup_scripts`，并通过显式检查 `$status` 传递退出码（不启用全局 `-e`，避免第三方 EDA `setup_*.csh` 脚本内部状态误中止）。
4. **`EMU_ROOT` 路径锚点、`-db` 简写与 `--comdir` 对称目录约定**：
   - `[env].emu_root` 必须配置为**绝对路径**，作为其他相对路径以及 `$EMU_ROOT` 引用的唯一锚点，并自动导出为环境变量 `EMU_ROOT`。
   - CLI **`-db <db_name>`（同时兼容 `--db`）**：传入 `<db_name>` 时**不需要加 `.toml` 后缀**，解析器自动补齐 `.toml`（若传入路径已带 `.toml` 后缀亦可直接识别）。
   - 若配置项中出现相对路径（非 `/` 开头、非 `$VAR` 开头），统一以 `EMU_ROOT` 为基准解析；CLI 路径参数（`--comdir`、`--db-path`、`--simdir`）遵循同样规则：绝对路径直接使用，相对路径统一以 `EMU_ROOT` 为基准解析（不额外引入 `--netlist-dir`）。
   - **统一 `--comdir` 下的前后端对称工作目录**（支持同 `--comdir` 下 1 个 netlist 挂 N 个 database 并行互不覆盖）：
     - **ICE 前端目录 `<comdir>/netlist/<netlist.name>/`**：`analysis`、`elaborate`、`syn` 的工作目录（产出 `va.lib`、`*.vg` 与 `netlist_manifest.toml`）。
     - **ICE 后端目录 `<comdir>/database/<database.name>/`**：`impt`、`precomp`、`comp` 的工作目录（按 `[database].netlist` 读取 `<comdir>/netlist/<netlist>/netlist_manifest.toml` 中的 `.vg`）。
     - **IXCOM 日常单文件目录 `<comdir>/database/<database.name>/`**：无 `[netlist]` 时，前端 `analysis`（`libmaprc` + 工作库）与后端 `ixcom`（`xc_work/`、`WORK/`）全程在同一目录内完成；若显式拆分 `[netlist]`，则 `analysis` 落在 `<comdir>/netlist/<netlist.name>/` 并通过 `-libmaprc` 复用。
5. **工具命令内置约定与模板自动渲染（依据 WXE 24.05 官方手册）**：
   - 各阶段二进制工具固定由模板调用，工具版本统一通过 `[env].setup_scripts`（`PATH`）控制，不在 TOML 中设置冗余的阶段级二进制覆盖字段：
     - ICE：`vavlog` / `vavhdl`（analysis）、`vaelab`（elaborate）、`xeCompile`（impt/precomp/comp）、`xeDebug`（sim）。
     - IXCOM：`vlan` / `vhan`（analysis）、`ixcom`（compile）、`xrun`（sim）。
   - *（注：`[comp].compile_cmd` 控制 `compile.qel` 内部的 XEL 编译命令如 `compile` / `compileFind`，而非外部 UNIX 工具路径。）*
   - 结构化字段（`-work <worklib>`、`-logFile` / `-log` / `-l`、`<topModule>` 位置参数、`-z2`/`-z3`、`-host`、`-session`、`-q "<queues>"`、QEL 文件名）由 Jinja2 模板自动渲染，禁止在 `opts` 中重复书写；不暴露 `qel_file` 作为配置项。
6. **LSF 统一调度规则**：
   - 全局在 `[env]` 中通过 `bsub = true/false` 统一开关集群调度，并配置默认 `queues`、`bsub_opts` 与 `[env.farm]`。`bsub = false` 时所有阶段本地 `tcsh` 直接执行。
   - 当 `[env].bsub = true` 时：
     - `analysis`、`elaborate`、`ixcom`、`sim` 阶段支持通过 `bsub` 提交（`vaelab` 亦支持原生 `-parallelLSFMultiBsub`，`emulator.pdf` P117–P120、`compileICE.pdf` P65）。
     - `impt`、`precomp`、`comp`（`xeCompile` 阶段）**不需要**配置 `bsub_opts` 或 `queues`，而是由专属工具 `tools/emu_gen_computefarm` 读取 `[env]` / `[env.farm]` 在编译目录生成官方格式 `computeFarm.json`（`emulator.pdf` P117–P119），并由 `import.qel` 自动附加 `designImport -useLSF`（`emulator.pdf` P123、`xecmdref.pdf` P231）或 `compile.qel` 在 PPC 模式下设置 `set PPC(computeFarm) "auto"`（`emulator.pdf` P117）。
7. **外围预处理职责解耦**：
   - `[[analysis.module]]` 作为唯一的 filelist 声明处；`[filelist]` 仅存放 `delete` / `replace` 清洗规则。
   - Filelist 清洗（`tools/emu_filelist_process`）、`computeFarm.json` 生成（`tools/emu_gen_computefarm`）与 `clocks.qel` 生成（`tools/emu_gen_clocks`，解析 DE 提供的时钟表格生成，避免大量时钟细节堆在 TOML 中）均拆分为**独立专属脚本工具**，共用同一份 `database.toml` 配置；`kemu` 本身专注脚本渲染与调度。
8. **用户自定义 Hook 机制（3 个 QEL Hook + Shell `extra_lines`）**：
   - QEL 层仅在 WXE 24.05 官方流程的关键节点保留 3 个显式可选 Hook（`[precomp].user_command_pre_precomp`、`[comp].user_command_pre_comp`、`[comp].user_command_post_comp`），Shell 层保留 `extra_lines`，平时省略不写，临时追加命令时无需修改 Python 代码。

---

## 2. TOML 书写风格与防坑规范

1. **文件编码与换行**：统一使用 UTF-8（无 BOM）编码和 LF（`\n`）换行符。
2. **统一使用单引号 `'...'`**：
   - 在 TOML 中单引号为字面量字符串（不解析反斜杠转义），普通路径/字符串与正则表达式写法完全一致，避免 `\` 双重转义心智负担。
   - 仅当字符串内容本身包含单引号 `'` 或必须使用 `\n`、`\t` 等转义序列时，才使用双引号 `"..."`。
3. **选项命名与书写规范（符合 EDA 工程习惯）**：
   - **Shell CLI 参数统一 `*_opts` 后缀（类型统一为 `list[str]`）**：`opts`、`vlog_opts`、`vhdl_opts`、`dut_opts`、`tb_opts`、`vaelab_opts`、`xecompile_opts`、`bsub_opts`。
   - **QEL/XEL 内置选项统一 `*_options` 后缀**：`compiler_options`、`precompile_options`（对应官方文件 `compilerOptions.qel` / `precompileOptions.qel`）。
   - **父子层同名追加**：`[analysis]` 与 `[[analysis.module]]` 使用同名字段 `vlog_opts`、`vhdl_opts`、`define_list`，模块级自动追加在全局之后。
   - **Hook 分层清晰**：QEL 补丁用 `user_command_*`（3 个节点），Shell 补丁用 `extra_lines`。
   - **每条完整选项写成一个字符串元素**，禁止将 flag 与参数值拆成两个数组元素：
     - 正确：`['-timescale 1ns/1ps', '-R "rusage[mem=256000]"']`
     - 错误：`['-timescale', '1ns/1ps']`
   - 禁止在 `opts` 中手写由模板自动渲染的 `-work`、`-logFile`、`-log`、`-q` 等结构化参数。
4. **子表位置陷阱**：
   - `[env.vars]`、`[env.farm]`、`[emulator.machines]`、`[[analysis.module]]`、`[[comp.symmetric]]`、`[sim.wave]`、`[sim.tdf]` 必须写在所属父 Section 普通键值对的**之后**。否则 TOML 解析器会将后面出现的普通键误归入子表。
5. **数组排版**：包含多项或较长路径的数组建议每项占一行，并保留尾逗号，便于 `git diff` 审阅。
6. **命名字符集约束**：`[netlist].name`、`[database].name`、`[database].netlist`、`[database].design_lib`、`[[analysis.module]].name`、`[[analysis.module]].worklib`、`[release].db_prefix` 直接用于文件名、目录名与库名，仅允许 `[A-Za-z0-9_-]+`。

---

## 3. Section 与字段详细规范

### 3.1 `[netlist]` 与 `[database]` — 前端网表与后端 Database 元信息

`[netlist]` 描述前端综合产物（`<comdir>/netlist/<netlist.name>/`），`[database]` 描述后端建库产物（`<comdir>/database/<database.name>/`）。两者既可写在同一份 TOML 中跑一站式流程，也可拆分为 `netlist.toml` 与多份 `database_*.toml` 实现 ICE 1 对 N 解耦；IXCOM 日常单文件则直接省略 `[netlist]`，在 `[database]` 中填写顶层模块名即可。

`[netlist]` 字段（ICE 前端或双文件前端必填；IXCOM 日常单文件可省略）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | **前端时是** | - | Netlist 名称（如 `'soc_rtl_v1'`），决定产出目录 `<comdir>/netlist/<name>/` |
| `design_top` | string | **前端时是** | - | DUT 顶层模块名（如 `'dut_top'`） |
| `testbench_top` | string | 否 | `''` | Testbench 顶层模块名（如 `'tb_top'`；ICE 并行 elaborate 与 IXCOM `-top` 时填写） |
| `platform` | string | 否 | 继承 `[emulator].target_system`（回退 `'Z2'`） | ICE `vaelab -Platform z2\|z3` 目标机型（`'Z2'` / `'Z3'` / `'Z3_Lsystem'`）；纯前端 `netlist.toml` 不含 `[emulator]` 时显式填写，`compileICE.pdf` P65 |
| `desc` | string | 否 | `''` | 简短描述，说明该 netlist 版本或用途 |

`[database]` 字段（后端编译、IXCOM、`sim`、`release` 时必填）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | **后端/仿真/打包时是** | - | Database 名称（如 `'base_fv'`），决定产出目录 `<comdir>/database/<name>/` 及 `release` 命名 |
| `netlist` | string | 否 | 同 `[netlist].name` | ICE 双文件解耦模式下指定复用的 netlist 名称，自动定位 `<comdir>/netlist/<netlist>/`；单文件同时写 `[netlist]` 时可省略；IXCOM 日常单文件不填 |
| `netlist_dir` | string | 否 | `''` | 可选逃生舱：跨 `--comdir` 复用外部历史 netlist 目录时显式指定（相对路径基于 `EMU_ROOT`），覆盖默认的 `<comdir>/netlist/<netlist>/` |
| `design_lib` | string | 否 | `'work'` | ICE 目标设计库名，供 `importOption {library <design_lib>}` 与 `design <design_lib> <top>` 共用（`compileICE.pdf` P94、`xecmdref.pdf` P232） |
| `design_top` | string | 否 | 继承 `[netlist]` 或 `netlist_manifest.toml` | IXCOM 日常单文件（不写 `[netlist]`）或直接导入外部裸 `.vg` 时必填（IXCOM 中用于 `+dut+<design_top>`） |
| `testbench_top` | string | 否 | 继承 `[netlist]` 或 `netlist_manifest.toml` | IXCOM 日常单文件或导入外部裸 `.vg` 时按需填写 |
| `desc` | string | 否 | `''` | 简短描述，说明该 database 的用途 |

```toml
# 示例 A：ICE 单文件一站式 / 双文件解耦写法（双文件时仅各自保留对应段）
[netlist]
name = 'soc_rtl_v1'
design_top = 'dut_top'
testbench_top = 'tb_top'
platform = 'Z2'
desc = 'min system RTL netlist'

[database]
name = 'base_fv'
netlist = 'soc_rtl_v1'   # 单文件同处存在 [netlist] 时可省略
design_lib = 'work'
desc = 'FV debug database'
```

```toml
# 示例 B：IXCOM 日常单文件写法（无需 [netlist]）
[database]
name = 'base_ixcom'
design_top = 'dut_top'
testbench_top = 'tb_top'
desc = 'min system IXCOM/SA database'
```

---

### 3.2 `[env]`、`[env.vars]` 与 `[env.farm]` — 运行环境与集群调度

所有与编译/仿真环境、集群调度及环境变量相关的参数均统一收口在 `[env]`、`[env.vars]` 与 `[env.farm]`，供后续阶段模板与 `tools/` 工具直接引用；Palladium 硬件机器池独立配置在 `[emulator]`。

`[env]` 字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `emu_root` | string | **是** | - | 项目根目录绝对路径（相对路径与 `$EMU_ROOT` 的唯一锚点）；自动在脚本第一行导出为 `setenv EMU_ROOT` |
| `setup_scripts` | list[str] | 否 | `[]` | 在 `setenv` `[env.vars]` 之后、每个 `.csh` 开头依次 `source` 的环境脚本列表 |
| `bsub` | bool | 否 | `false` | 全局 LSF 调度开关；`false` 时本地 `tcsh` 执行，`true` 时前端/仿真走 `bsub` 提交，且由 `tools/emu_gen_computefarm` 生成 `computeFarm.json` 供 `xeCompile` 使用集群 |
| `queues` | list[str] | 否 | `[]` | 全局默认 LSF 队列列表（用于 `bsub -q` 及供 `tools/emu_gen_computefarm` 生成 `computeFarm.json`） |
| `bsub_opts` | list[str] | 否 | `[]` | 全局公共 `bsub` 附加参数（如 `['-Is']`），每条完整选项一个字符串 |

`[env.vars]` 字段（**可选**）：

仅包含需要在脚本开头 `setenv` 的 **WXE 24.05 官方环境变量** 或项目自定义变量（无额外变量时整段可省略）。遇到 `XE_HOST_FILE` 时模板自动先执行 `unsetenv XE_HOST`（`emulator.pdf` P16）。常用已核验的 WXE 24.05 官方环境变量如下：

| 官方变量名 | 常用取值 | 用途与依据 |
|---|---|---|
| `XE_NOECHO` | `'1'` | 抑制 `xeDebug` 脚本命令回显，等效 `-noecho`（`xecmdref.pdf` P203） |
| `XE_FSDB_VERSION` | `'58'` / `'57'` | 指定 Verdi FSDB 输出版本（`GenericSettingUp_PD.pdf` P50、`xecmdref.pdf` P204） |
| `XE_ICE_FAST_DOWNLOAD` / `XE_SA_FAST_DOWNLOAD` | `'1'` / `'0'` | 启用 ICE / SA 快速下载（`GenericSettingUp_PD.pdf` P50, P53） |
| `XE_BP_WITH_SYMCONFG` | `'1'` / `'<host\|file>'` | 运行期按 `.bp` 约束匹配 `symmetricConfiguration` 落点（`GenericSettingUp_PD.pdf` P48） |
| `XE_RESERVE_KEY` / `XE_USE_RESERVED_ONLY` | `'<key>'` / `'1'` | 绑定资源预留 key 或仅使用已预留资源（`GenericSettingUp_PD.pdf` P53–P54、`xecmdref.pdf` P945） |
| `XE_SECURE_CONNECTION` | `'1'` | 远端读取 `*.et3confg` 时使用 SSH 安全连接（`GenericSettingUp_PD.pdf` P53、`xecmdref.pdf` P354） |
| `DBE_HOST` / `XE_DYNP` | `'<host>'` / `'1'` | SA 模式下指定 DBEngine 主机或启用 DYNP 调试模式（`GenericSettingUp_PD.pdf` P55、`emulator.pdf` P15–P16） |

`[env.farm]` 字段（**可选**；供 `tools/emu_gen_computefarm` 生成官方 `computeFarm.json`，见 `emulator.pdf` P117–P119；省略时由工具基于 `[env].queues` 生成默认资源配置）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `farm_name` | string | 否 | `'LSF'` | 集群调度器类型（`'LSF'` / `'NC'` / `'custom'`，映射 `farmName`） |
| `full_design` | string | 否 | `''` | 对应 `farmOptions.FullDesign` |
| `partitions` | string | 否 | `''` | 对应 `farmOptions.Partitions` |
| `buckets` | string | 否 | `''` | 对应 `farmOptions.Buckets` |
| `import` | string | 否 | `''` | 对应 `farmOptions.Import` |
| `dbg_prepare` | string | 否 | `''` | 对应 `farmOptions.dbgPrepare` |

```toml
[env]
emu_root = '/proj/soc/emu'
setup_scripts = [
  '$EMU_ROOT/env/setup_palladium.csh',
]
bsub = false
queues = [
  'verif_r8',
  'design_r8',
]
bsub_opts = [
  '-Is',
]

[env.vars]
XE_NOECHO = '1'
XE_ICE_FAST_DOWNLOAD = '1'
XE_FSDB_VERSION = '58'

[env.farm]
farm_name = 'LSF'
full_design = '-M 200000 -q design_r8'
partitions = '-M 150000 -R "rusage[mem=40000]" -q design_r8'
buckets = '-M 500000 -q design_r8'
import = '-M 200000 -q design_r8'
dbg_prepare = '-M 150000 -q design_r8'
```

---

### 3.3 `[emulator]` 与 `[emulator.machines]` — Palladium 硬件机器池与激活目标

将所有 Palladium 硬件机器映射与当前激活目标从 `[env]` 独立出来，支持在 `[emulator.machines]` 中用 TOML 1.0 inline table 集中维护多台机器（`host` 与 `et3confg` 一一绑定），切换机器时只需修改 `[emulator].active` 一行，并可在 `[[comp.symmetric]]` 中按别名复用。

`[emulator]` 字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `active` | string | **涉及硬件编译/仿真时是** | `''` | 当前激活的机器别名，必须对应 `[emulator.machines]` 中的 key；切换目标硬件仅需改此行 |
| `target_system` | string | 否 | `'Z2'` | 默认 Palladium 目标机型（`'Z2'` / `'Z3'` / `'Z3_Lsystem'`）；映射为 `vaelab -Platform z2\|z3` 与 `xeCompile`/`xeDebug` 的 `-z2\|-z3`（`compileICE.pdf` P65、`xecmdref.pdf` P195, P202） |

`[emulator.machines]` 字段（推荐使用 TOML inline table `alias = { host = '...', et3confg = '...' }`；字段较多时也可展开为 `[emulator.machines.<alias>]` 子表，两者解析结果完全等价）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `host` | string | **是** | - | Palladium 硬件主机名（如 `'horizon_z2'`）；用于 `xeDebug -host`、`run.tcl` 的 `host <host> -path [pwd]`；当 `et3confg` 为空时也用于 `emulatorConfiguration -add {host ...}` 与 SA `XE_HOST`（`emulator.pdf` P15–P17、`xecmdref.pdf` P202, P911） |
| `et3confg` | string | 否 | `''` | `.et3confg` 配置文件路径（支持绝对路径、`$EMU_ROOT/...` 或相对 `[env].emu_root` 路径）；非空时编译与 SA 仿真优先映射为 `emulatorConfiguration -add {file ...}` 与 `XE_HOST_FILE`（模板自动先 `unsetenv XE_HOST`，`emulator.pdf` P15–P17、`xecmdref.pdf` P353–P354） |
| `target_system` | string | 否 | 继承 `[emulator].target_system` | 可选，单机覆写目标机型（如混合维护 Z2 与 Z3 机器池时） |

```toml
[emulator]
active = 'horizon_z2'
target_system = 'Z2'

[emulator.machines]
horizon_z2 = { host = 'horizon_z2', et3confg = '/match3/scd.et3confg' }
emu_z2 = { host = 'emu_z2', et3confg = 'match3/scd.et3confg.emu_z2' }
```

---

### 3.4 `[filelist]` — 源码清洗规则（供独立预处理工具使用）

`[filelist]` 仅定义清洗规则，供独立工具 `tools/emu_filelist_process` 读取同一份 `database.toml` 对 `[[analysis.module]]` 中声明的 filelist 执行预处理；不在此处重复声明 filelist 路径。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `delete` | list[str] | 否 | `[]` | 正则表达式列表；命中任意一条的行将被删除（先执行） |
| `replace` | list[list[str]] | 否 | `[]` | 有序二元数组列表 `[['old_regex', 'new_str'], ...]`；按顺序对每一行执行正则替换（后执行） |

```toml
[filelist]
delete = [
  'sim_only_model\.sv$',
  '^\s*//',
]
replace = [
  ['rtl/mem/sram_behav\.v', 'emu/mem/sram_emu.v'],
  ['\+define\+SIM_ONLY', '+define+PALLADIUM'],
]
```

---

### 3.5 `[analysis]` 与 `[[analysis.module]]` — 按模块分析（ICE `vavlog`/`vavhdl` 与 IXCOM `vlan`/`vhan`）

对应 `kemu build ice --act analysis`（生成 `va.lib` + `vavlog`/`vavhdl`，`compileICE.pdf` P49–P58）以及 `kemu build ixcom --act analysis`（生成 `libmaprc` + `vlan`/`vhan`，`compileIXCOM.pdf` P32–P34、`xecmdref.pdf` P972, P1007）。  
以 `module` 作为最小编译粒度：大到整个 `dut_top` 全量 RTL，小到单个子系统或单文件均可统一配置。`-work <worklib>` 与日志参数（ICE 为 `-logFile`，IXCOM 为 `-l`）由模板自动渲染。

`[analysis]` 字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `max_workers` | int | 否 | `4` | `[[analysis.module]]` 多线程并发编译上限 |
| `bsub_opts` | list[str] | 否 | `[]` | 追加在 `[env].bsub_opts` 之后的阶段级 `bsub` 选项（仅 `bsub = true` 生效） |
| `queues` | list[str] | 否 | 继承 `[env].queues` | 可选，覆盖本阶段队列 |
| `vlog_opts` | list[str] | 否 | `[]` | 所有模块共享的 Verilog analysis 额外选项（ICE 模板 `analysis_vlog.csh.j2` 已内置 `-sv` 与 `-db2`） |
| `vhdl_opts` | list[str] | 否 | `[]` | 所有模块共享的 VHDL analysis 额外选项（ICE 模板 `analysis_vhdl.csh.j2` 已内置 `-V2008` 与 `-db2`，见 `compileICE.pdf` P52） |
| `define_list` | list[str] | 否 | `[]` | 所有 Verilog/SV 模块共享的宏定义列表（写纯宏名或 `MACRO=VAL`，模板自动渲染为 `+define+<item>` 传给 `vavlog`/`vlan`，见 `compileICE.pdf` P58、`xecmdref.pdf` P1007, P1020；不作用于 VHDL） |

`[[analysis.module]]` 单项字段（执行 `analysis` / `syn` 时至少配置 1 个）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | **是** | - | 编译模块名（按语言拆分为独立脚本：`analysis_<name>_vlog.csh` / `analysis_<name>_vhdl.csh` 或 `vlan`/`vhan` 脚本） |
| `worklib` | string | 否 | 同 `name` | 编译目标库名，自动写入 `va.lib` / `libmaprc` 并渲染为 `-work <worklib>` |
| `verilog_filelist` | list[str] | 否 | `[]` | Verilog/SystemVerilog filelist 列表（ICE 用 `-f`，与 `vhdl_filelist` 至少填一项） |
| `vhdl_filelist` | list[str] | 否 | `[]` | VHDL filelist 列表（ICE `vavhdl` 用 `-file`，与 `verilog_filelist` 至少填一项） |
| `define_list` | list[str] | 否 | `[]` | 模块独有的 Verilog/SV 宏定义列表，追加在 `[analysis].define_list` 之后并渲染为 `+define+<item>` |
| `vlog_opts` | list[str] | 否 | `[]` | 追加在 `[analysis].vlog_opts` 之后的模块级 Verilog 选项 |
| `vhdl_opts` | list[str] | 否 | `[]` | 追加在 `[analysis].vhdl_opts` 之后的模块级 VHDL 选项 |

```toml
[analysis]
max_workers = 4
define_list = [
  'PALLADIUM',
]
vlog_opts = [
  '-timescale 1ns/1ps',
]

[[analysis.module]]
name = 'dut_top'
worklib = 'dut_lib'
verilog_filelist = [
  '$EMU_ROOT/rtl/flist/dut_verilog_flat.f',
  '$EMU_ROOT/rtl/flist/palladium/mmp.f',
  '$EMU_ROOT/rtl/flist/palladium/memory_module.f',
]
vhdl_filelist = [
  '$EMU_ROOT/rtl/flist/dut_vhdl_flat.f',
]
define_list = [
  'DUT_ICE',
]

[[analysis.module]]
name = 'tb_top'
worklib = 'tb_lib'
verilog_filelist = [
  '$EMU_ROOT/tb/flist/tb_verilog_flat.f',
]
define_list = [
  'ICE_TB',
]
```

---

### 3.6 `[elaborate]` — ICE 顶层并行展开与综合（`vaelab`）

对应 `kemu build ice -db <db_name> --comdir <path> --act elaborate`（以及 `--act syn` 的第二步）。依据 `compileICE.pdf` P58–P68，`vaelab` 接受顶层名作为位置参数 `vaelab <topModule> -logFile <log> -outputVlog <name>.vg -vaLib va.lib`（不接受 `-top`），跨库使用 `-refLib`。默认在 `<comdir>/netlist/<netlist.name>/` 并发执行 `[netlist].design_top` 与 `[netlist].testbench_top` 两路 `vaelab`，完成后自动生成产物契约 `netlist_manifest.toml`。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `bsub_opts` | list[str] | 否 | `[]` | 阶段级 `bsub` 附加选项 |
| `queues` | list[str] | 否 | 继承 `[env].queues` | 可选，覆盖本阶段队列 |
| `opts` | list[str] | 否 | `[]` | `design` 与 `testbench` 共用的 `vaelab` 额外选项（如 `'-alu'`、`'-parallel 4'`、`'-parallelLSFMultiBsub 4'`） |
| `dut_opts` | list[str] | 否 | `[]` | 仅用于 `[netlist].design_top` 的 `vaelab` 额外选项 |
| `tb_opts` | list[str] | 否 | `[]` | 仅用于 `[netlist].testbench_top` 的 `vaelab` 额外选项 |
| `extra_lines` | list[str] | 否 | `[]` | 追加到 `elaborate` 脚本中的自定义 shell 行 |

```toml
[elaborate]
opts = [
  '-alu',
]
```

---

### 3.7 `[impt]` — ICE 导入网表（`xeCompile import.qel`）

对应 `kemu build ice -db <db_name> --comdir <path> --act impt`。依据 `xecmdref.pdf` P230–P232 与 `compileICE.pdf` P17–P18，模板使用 `importOption`、`netlistFile`、`refLib` 与 `designImport`（当 `[env].bsub = true` 时自动附加 `-useLSF`，`emulator.pdf` P123），并渲染 `impt.csh` 调用 `xeCompile [-z2|-z3] -log impt.log import.qel`（`xecmdref.pdf` P194–P195）。默认自动从 `<comdir>/netlist/<netlist>/netlist_manifest.toml` 读取 `.vg` 路径，若无须覆写则**整个 `[impt]` Section 可省略**。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `mode` | string | 否 | `'full'` | 网表导入模式：`'full'` 或 `'incr'`（映射 `importOption {mode ...}`） |
| `ref_libs` | list[str] | 否 | `['qtref', 'generic']` | 导入阶段参考库列表（映射 `refLib ...`） |
| `netlist_files` | list[str] | 否 | `[]` | 仅当导入外部现成 `.vg`（无 `netlist_manifest.toml`）时显式填写 `.vg` 路径列表；常规流程自动读取 manifest |
| `extra_netlists` | list[str] | 否 | `[]` | 额外 `netlistFile {verilog ...}` / `{vhdl ...}` 语句列表 |
| `opts` | list[str] | 否 | `[]` | 传给 `xeCompile` 的额外命令行参数 |

```toml
[impt]
mode = 'full'
ref_libs = [
  'qtref',
  'generic',
]
```

---

### 3.8 `[precomp]` — ICE 预编译检查与 DB 裁剪（`xeCompile precompile.qel`）

对应 `kemu build ice -db <db_name> --comdir <path> --act precomp`。依据 `compileICE.pdf` P94, P113 与 `xecmdref.pdf` P316, P353, P366, P374–P375, P393, P407–P408, P546：
- 渲染生成 `compilerOptions.qel`（由 `[comp].compiler_options` 与 `[comp].flow` 合成，并在 `precompile` **之前**执行 `source compilerOptions.qel`——严格满足 `xecmdref.pdf` P316 *"must be executed before running the precompile and icePrepare command sequence"*）、`precompileOptions.qel`、`keepNets.qel`、`precompile.qel` 与 `precomp.csh`，并在配置了 `clocks_qel` 时引入外部 `clocks.qel`。
- `precompile.qel` **不写入** `emulatorConfiguration`（`precompile` 阶段不使用硬件配置，`xecmdref.pdf` P353），环境变量由 `precomp.csh` 头部统一导出，集群调度由 `[env].bsub` 与 `computeFarm.json` 控制。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `opts` | list[str] | 否 | `[]` | 传给 `xeCompile` 的额外命令行参数 |
| `precompile_options` | list[str] | 否 | `[]` | 渲染为 `precompileOption -add ...` 到 `precompileOptions.qel`；含空格的带参数项（如 `'cdc my.cdc'`、`'loopsDepth 10'`）由模板自动补 `{...}` 包裹；保留裁剪边界端口为 keepNet 可追加 `'keepStubInputs'` / `'keepStubOutputs'`（`xecmdref.pdf` P366, P393, P407–P408） |
| `keep_nets` | list[str] | 否 | `[]` | 渲染为 `keepNet -add <net>` 到 `keepNets.qel`（`xecmdref.pdf` P375） |
| `clocks_qel` | string | 否 | `''` | 外部 `clocks.qel` 路径（由 `tools/emu_gen_clocks` 解析 DE 时钟表格生成，不在 TOML 中罗列时钟明细） |
| `module_stubs` | list[str] | 否 | `[]` | 按模块名做 DB 裁剪，渲染为 `moduleStub -add {<LIB> <cellName>}`；只写模块名如 `'gpu_core'` 时自动补 `[database].design_lib`，含空格写 `'<LIB> <cellName>'` 如 `'* pcie_phy*'` 则原样输出（支持 `*`/`?` 通配符，`xecmdref.pdf` P393） |
| `instance_stubs` | list[str] | 否 | `[]` | 按层次实例路径做 DB 裁剪，渲染为 `instanceStub -add {<inst_path>}`（支持 `*`/`?` 通配符，`xecmdref.pdf` P366） |
| `user_command_pre_precomp` | list[str] | 否 | `[]` | 紧接 `precompile` 之前注入的临时 XEL 命令（如 `breakNet`、`tieNet`、`memoryTransform` 等；平时省略） |

```toml
[precomp]
precompile_options = [
  'asyncReset',
  'loopsDepth 10',
  'keepStubInputs',
]
keep_nets = [
  'dut_top.clk_gen.*',
]
clocks_qel = '$EMU_ROOT/qel/clocks.qel'
module_stubs = [
  'gpu_core',
  '* pcie_phy*',
]
instance_stubs = [
  'dut_top.u_npu.u_core0',
]
```

---

### 3.9 `[comp]` 与 `[[comp.symmetric]]` — Database 最终编译与 Symmetric Compile

对应 `kemu build ice -db <db_name> --comdir <path> --act comp`（以及 IXCOM 的自定义 `compile.qel`）。依据 `compileICE.pdf` P117–P118、`emulator.pdf` P15–P29, P117 与 `xecmdref.pdf` P316–P317, P353–P354, P459–P461, P545–P546：
- `compile.qel` 严格遵循官方执行时序：`design` -> `source compilerOptions.qel`（含 `mode`、`visionMode` 与 PPC `distributedMulticore ON`）-> `emulatorConfiguration` / `symmetricConfiguration` -> `target_compile_scripts` -> `user_command_pre_comp` ->（按需 `icePrepare`）-> `compile_cmd` -> `user_command_post_comp`。
- **注意**：修改了影响前端预处理的 `compiler_options`（如 `mode`、`visionMode` 或切换 `flow = 'ppc'`）时，需同步重跑 `precomp` 使 `precompile` 与编译期选项保持一致（`xecmdref.pdf` P316）。
- 支持三档渐进配置 `symmetricConfiguration`：不写则不启用；单机扩域仅需在 `[comp]` 写一行 `symmetric_boards`；多机 / 指定落点 / `advancedPlacements` 场景通过 `[[comp.symmetric]]` 配置（不可同时写 `symmetric_boards` 与 `[[comp.symmetric]]`）。

`[comp]` 字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `flow` | string | 否 | `'unified'` | 编译流类型：`'unified'` 或 `'ppc'`（`flow = 'ppc'` 时自动向 `compilerOptions.qel` 注入 `{distributedMulticore ON}`，`xecmdref.pdf` P316；当 `bsub = true` 时同时写入 `set PPC(computeFarm) "auto"`，`emulator.pdf` P117） |
| `compiler_options` | list[str] | 否 | `['mode ice', 'visionMode FV']` | 渲染为 `compilerOption -add {<item>}` 到 `compilerOptions.qel`（`precomp` 与 `comp` 共用）；在基线 `['mode ice', 'visionMode FV']` 之上按 key 合并（同 key 覆盖如 `'visionMode DYNP'`，新 key 追加如 `'symmetricRotationalFits ON'`；`compileICE.pdf` P94、`emulator.pdf` P24, P29） |
| `boards` | string | 否 | `''` | base configuration 板卡/域分配（支持 `'*'`、`'0-5'`、`'0+1+2'`、`'0.0+0.1'`，`emulator.pdf` P17–P20） |
| `symmetric_boards` | string | 否 | `''` | 快捷单机扩域配置，复用 `[emulator]` 激活机器的 `et3confg` / `host` 生成 `symmetricConfiguration -add ... {boards <str>}`；写 `'ALL'` 时省略 `{boards ...}` 扩到整机（`xecmdref.pdf` P459） |
| `target_compile_scripts` | list[str] | 否 | `[]` | 可选，Target System / SpeedBridge 编译期 `.qel` 脚本列表（含 `terminalAssign`、`terminalTiming`、`delayBox`、`cableConnection` 等；在 `precompile` 之后、`icePrepare` 之前 `source`，`xecmdref.pdf` P545） |
| `ice_prepare` | bool | 否 | `false`（配了 `target_compile_scripts` 时默认 `true`） | 是否在 `compile` 前执行 `icePrepare`（仅连接 Target System 时需要，`xecmdref.pdf` P545） |
| `compile_cmd` | string | 否 | `'compile'` | 最终编译 XEL 命令（如 `'compile'`、`'compile -names_crit'`、`'compileFind -lsf'`，`compileICE.pdf` P118） |
| `opts` | list[str] | 否 | `[]` | 传给 `xeCompile` 的额外命令行参数 |
| `user_command_pre_comp` | list[str] | 否 | `[]` | 位于 `target_compile_scripts` 之后、`icePrepare`/`compile` 之前的临时 XEL 命令（平时省略） |
| `user_command_post_comp` | list[str] | 否 | `[]` | 位于 `compile` 之后的收尾/报告 XEL 命令（如 `hwInfo` 等；平时省略） |

`[[comp.symmetric]]` 单项字段（多机 / 指定落点 / 高级重定位场景按需填写）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `emulator` | string | 否 | `''` | 引用 `[emulator.machines]` 中的机器别名（自动解析为其 `et3confg` 或 `host`；与 `host` / `file` 三选一，三者均省略则复用 `[emulator].active`） |
| `host` | string | 否 | `''` | 直接指定目标 emulator 主机名（与 `emulator` / `file` 三选一） |
| `file` | string | 否 | `''` | 直接指定目标 `.et3confg` 路径（与 `emulator` / `host` 三选一） |
| `boards` | list[str] | 否 | `[]` | 限制搜索域列表（每项生成一个 `{boards <domain_str>}`；与 `locations` 均为空时扩到整机，`xecmdref.pdf` P459–P460） |
| `locations` | list[str] | 否 | `[]` | 显式保证落点列表（每项生成一个 `{location <domain_str>}`，`xecmdref.pdf` P460） |
| `advanced_placements` | string | 否 | `''` | 激进搜索上限（整数字符串或 `'MAX'`；仅配置 `boards` 时生效，`emulator.pdf` P28、`xecmdref.pdf` P460） |

```toml
# 常用写法（Unified 默认流 + DYNP 覆盖 + 单机扩域）
[comp]
flow = 'unified'
compiler_options = [
  'visionMode DYNP',
]
boards = '0-5'
symmetric_boards = '0-17'
```

```toml
# 高级 PPC 多机 / Target / advancedPlacements 写法
[comp]
flow = 'ppc'
boards = '0.0+0.1'
target_compile_scripts = [
  '$EMU_ROOT/qel/target_assign.qel',
]
ice_prepare = true

[[comp.symmetric]]
emulator = 'emu_z2'
boards = ['0.0+0.1+0.2+0.3']
advanced_placements = 'MAX'

[[comp.symmetric]]
host = 'neon17'
locations = ['0.2+0.3']
```

---

### 3.10 `[ixcom]` — IXCOM（SA）编译配置（`vlan`/`vhan`/`ixcom`）

对应 `kemu build ixcom -db <db_name> --comdir <path> [--act analysis|swmodel|hdlice|xecompile|all] [--gen-only]`（`-db` 无需 `.toml` 后缀）。依据 `compileIXCOM.pdf` P17–P50, P189–P216, P306、`emulator.pdf` P15–P16 与 `xecmdref.pdf` P972, P1007, P1058：
- 多步模式使用 `libmaprc` + `vlan`/`vhan` + `ixcom -target <stage>`；单步模式使用 `ixcom` 直接编译。
- 硬件目标通过环境变量 `XE_HOST`（或互斥的 `XE_HOST_FILE`）与 `XE_BOARDS` 传入。
- 官方建议优先使用 `compilerOptions.qel` 引导 IXCOM 编译流程（`compileIXCOM.pdf` P49），仅在确有需要时开启 `use_custom_impt_qel` / `use_custom_comp_qel`。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `compile_mode` | string | 否 | `'multi'` | IXCOM 编译模式：`'multi'`（分步 `swmodel` -> `hdlice` -> `xecompile`）或 `'single'`（单步） |
| `hw_mode` | bool | 否 | `true` | `true` 编译硬件加速（`+1xua` + `hdlice` + `xecompile`）；`false` 仅软件仿真模型 |
| `parallel_hdlice` | int | 否 | `4` | 传递 `-parallelHdliceAnalyze <N>` / `-vaelabargs "... -parallel <N>"`（`compileIXCOM.pdf` P39–P40, P190） |
| `dump_mode` | string | 否 | `'online'` | 波形模式：`'online'` 或 `'offline'`（`offline` 自动附加 `-enableLWD` 并运行 `ixcom -target lwdmodel`，`compileIXCOM.pdf` P210） |
| `vaelab_opts` | list[str] | 否 | `[]` | 透传给 `-vaelabargs` 的额外选项列表（如 `['-alu', '-minMemSize 64']`） |
| `xecompile_opts` | list[str] | 否 | `[]` | 透传给 `-xecompileargs` 的额外选项列表（如 `['-mcBucket']`） |
| `use_custom_impt_qel` | bool | 否 | `false` | 是否生成并通过 `-xeCompile import=import.qel` 传给 `ixcom` |
| `use_custom_comp_qel` | bool | 否 | `false` | 是否生成并通过 `-xeCompile compile=compile.qel` 传给 `ixcom` |
| `opts` | list[str] | 否 | `[]` | 传给 `ixcom` 的额外命令行参数 |
| `bsub_opts` | list[str] | 否 | `[]` | 阶段级 `bsub` 附加选项 |
| `queues` | list[str] | 否 | 继承 `[env].queues` | 可选，覆盖本阶段队列 |

```toml
[ixcom]
compile_mode = 'multi'
hw_mode = true
parallel_hdlice = 4
dump_mode = 'online'
vaelab_opts = [
  '-alu',
]
```

---

### 3.11 `[sim]`、`[sim.wave]` 与 `[sim.tdf]` — 运行期仿真、波形与触发配置（ICE `xeDebug` / IXCOM `xrun -R`）

对应 CLI：

```csh
kemu sim ice   -db <db_name> --db-path <path> --simdir <path> --session <session_name> [--gen-only]
kemu sim ixcom -db <db_name> --db-path <path> --simdir <path> --session <session_name> [--gen-only]
```

`[sim]` 中**不配置 `db_path`**，而是由 CLI `--db-path` 传入。依据 `DebuggingDesigns.pdf` P14, P27–P31、`emulator.pdf` P13, P16、`SDL.pdf` P131–P149 与 `xecmdref.pdf` P202–P203, P598, P605–P614, P620–P621, P629, P686–P687, P784–P786, P811–P813, P833–P859, P901, P911, P1587：
- **ICE 模式**：从 `[emulator]` 激活机器读取 `host` 与 `target_system`，`sim.csh` 启动 `xeDebug [-z2|-z3] [-host <emu_host>] -session <session> -log sim.log -init run.tcl`（不加 `-gui` 默认就是命令行模式，自动附带 `-noecho`）。`run.tcl` 按官方顺序渲染：`debug <db_path> -session <session>` -> `host <emu_host> -path [pwd]`（`emulator.pdf` P13 明确推荐显式加 `-path [pwd]`，避免远端主机把目录自动转为 `/net/<host>/...` 导致路径不可达或性能下降）-> `download` ->（可选 `configPM` / `target_run_scripts` / `[sim.wave]` + `[sim.tdf]` / `tcl_file` / `run_cmd` / 收尾）。
- **IXCOM 模式**：根据 `[emulator]` 激活机器设置 `XE_HOST`（或互斥 `XE_HOST_FILE`，可选 `DBE_HOST` 通过 `[env.vars]` 配置），执行 `xrun -R -xmlibdirname <db_path> -l sim.log -input run.tcl`；`run.tcl` 统一消费同一套 `target_run_scripts`、`[sim.wave]`、`[sim.tdf]`、`tcl_file`、`run_cmd` 与 runtime Hook。
- **Probe 直接内插**：`[sim.wave]` 的 `probes` 与 `probe_scripts` **直接插入**到 `run.tcl` 和 `gen_fsdb_offline.tcl` 中（不单独生成中间 `probe.tcl`）。
- **TDF 与 `[sim.wave].enable` 联动**：配置了 `[sim.tdf]` 时，`kemu` 按 `trigger.tdf.j2` 渲染生成 `<simdir>/<tdf.name>`（或采用外部 `tdf_file`）；当 `[sim.wave].enable = true` 时，自动在 `run.tcl` 波形配置后注入 `sdl -setFile` / `sdl -load` / `sdl -enable`（以及可选 `sdl -haltOnTrigger 1` / `sdl -auto on`）。
- **不硬编码 `run -nowait`**：`xecmdref.pdf` P1587 已将 `run -nowait` 列入 Deprecated；模板仅在显式配置 `[sim].run_cmd` 时输出对应 `run` 命令，留空时完全交由用户的 `tcl_file` 或 `XE>` 交互终端控制。

`[sim]` 字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `bsub_opts` | list[str] | 否 | `[]` | 阶段级 `bsub` 附加选项 |
| `queues` | list[str] | 否 | 继承 `[env].queues` | 可选，覆盖本阶段队列 |
| `tcl_file` | string | 否 | `''` | 用户业务仿真运行脚本路径（如 `'$EMU_ROOT/sim/run_ice.tcl'`），在配置好主机/下载/波形后 `source` |
| `opts` | list[str] | 否 | `[]` | 仿真启动额外命令行参数（`sim ice` 传给 `xeDebug`，未传 `'-gui'` 时自动附带 `'-noecho'`；`sim ixcom` 传给 `xrun -R`） |
| `pm_mode` | string | 否 | `''` | ICE `configPM` 运行模式切换（`''` 不切换，可选 `'la'` / `'stb'` / `'vd'`，`xecmdref.pdf` P598） |
| `target_relocate_script` | string | 否 | `''` | 可选，ICE 下载前设置 `xeset targetRelocateScript <script.xel>`（`xecmdref.pdf` P911） |
| `target_run_scripts` | list[str] | 否 | `[]` | 可选，Target / SpeedBridge 运行期初始化脚本（`download` 之后 `source`） |
| `run_cmd` | string | 否 | `''` | 可选，显式运行指令（如 `'run'`、`'run 100ms'`、`run -continue`，`xecmdref.pdf` P812–P813）；留空则不输出 `run` |
| `auto_exit` | bool | 否 | `false` | 批处理跑完是否自动输出 `exit` 退出会话（默认 `false`，避免交互调试误退出） |
| `user_command_post_download` | list[str] | 否 | `[]` | `download` 与 `target_run_scripts` 之后注入的 Tcl/XEL 命令（如 `memory -load` 等；平时省略） |
| `user_command_pre_run` | list[str] | 否 | `[]` | `source <tcl_file>` 之后、`run_cmd` 之前注入的 Tcl/XEL 命令（平时省略） |
| `user_command_post_run` | list[str] | 否 | `[]` | `run_cmd` 之后注入的 Tcl/XEL 命令（平时省略） |
| `extra_lines` | list[str] | 否 | `[]` | 仿真脚本 `sim.csh` 中追加的自定义 tcsh 命令（如调用离线波形提取等） |

`[sim.wave]` 字段（**可选子表**，仅需工具托管波形采集/离线提取时展开，默认 `enable = false`）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `enable` | bool | 否 | `false` | 是否在 `run.tcl` 中启用波形控制（同时控制 `[sim.tdf]` 自动插入） |
| `mode` | string | 否 | `'offline'` | 波形收集方式（ICE 用）：`'offline'`（`database -prepareOffline`）或 `'online'`（`database -upload`）（`xecmdref.pdf` P614） |
| `name` | string | 否 | `'wave'` | 波形数据库名（`database -open <name>`，ICE offline 对应 `<name>.phy` / IXCOM 对应 `<name>.shm`） |
| `continuous_upload` | bool | 否 | `false` | ICE 是否附加 `-continuousupload`（`mode = 'offline'` 时自动追加 `-phy`，`xecmdref.pdf` P608–P609） |
| `num_files` | int | 否 | `0` | 离线提取 `gen_fsdb_offline.tcl` 的 `database -batch -numFiles <N>` 分片数（`0` 不传 `-numFiles`，`xecmdref.pdf` P606） |
| `time_unit` | string | 否 | `'ns'` | 对应 `xeset timeUnit`（空字符串则不输出） |
| `trigger_pos` | int | 否 | `50` | 对应 `xeset triggerPos`（`0`–`100` 百分比） |
| `trace_mem_size` | string | 否 | `''` | 对应 `xeset traceMemSize`（如 `'64M'`；空则沿用工具默认） |
| `probe_scripts` | list[str] | 否 | `[]` | 可选，外部 `probe` 定义脚本路径列表（直接在 `run.tcl` / `gen_fsdb_offline.tcl` 按序加载，带 `[file exists]` 检查） |
| `probes` | list[str] | 否 | `[]` | 可选，直接插入 `run.tcl` / `gen_fsdb_offline.tcl` 的内联 `probe ...` 命令列表（`xecmdref.pdf` P784–P786） |

`[sim.tdf]` 字段（**可选子表**，用于模板渲染 SDL `.tdf` 文件或引用外部 `tdf_file`；当 `[sim.wave].enable = true` 时自动写入 `run.tcl`）：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | 否 | `'trigger.tdf'` | 模板渲染输出的 SDL 文件名（位于 `<simdir>/<name>`） |
| `tdf_file` | string | 否 | `''` | 可选，直接复用外部已有 `.tdf` 文件路径（与下方内联渲染字段互斥） |
| `scope` | string | 否 | `''` | SDL 层次作用域（渲染 `scope <scope>;`，`SDL.pdf` P133） |
| `trigger_pos` | int | 否 | `None` | 可选，在 `.tdf` 中覆写 `triggerPos = <0..100>;`（与 `post_trigger_samples` 互斥，`SDL.pdf` P137） |
| `post_trigger_samples` | int | 否 | `None` | 可选，在 `.tdf` 中设置触发后采集 FCLK 周期数 `postTriggerSamples = <N>;`（与 `trigger_pos` 互斥，`SDL.pdf` P139） |
| `enable1` / `enable2` | string | 否 | `''` | 可选，计数器递减使能条件 `ENABLE1 = <expr>;` / `ENABLE2 = <expr>;`（`SDL.pdf` P141） |
| `counter1` / `counter2` | int | 否 | `None` | 可选，计数器初值 `COUNTER1 = <val>;` / `COUNTER2 = <val>;`（`SDL.pdf` P143） |
| `aliases` | dict[str, str] | 否 | `{}` | 可选，SDL 信号别名定义表（渲染为 `<name> = <expr>;`，`SDL.pdf` P131） |
| `triggers` | list[str] | 否 | `[]` | 全局触发条件列表（渲染为 `TRIGGER = <expr>;`，`SDL.pdf` P145） |
| `acquire` | list[str] | 否 | `[]` | 全局条件采集条件列表（渲染为 `ACQUIRE = <expr>;`，与 `no_acquire` 互斥，`SDL.pdf` P147） |
| `no_acquire` | list[str] | 否 | `[]` | 全局暂停采集条件列表（渲染为 `NO_ACQUIRE = <expr>;`，与 `acquire` 互斥，`SDL.pdf` P149） |
| `extra_lines` | list[str] | 否 | `[]` | 可选，追加完整 `INSTANCE`/`STATE` 状态机块等原始 SDL 语句 |
| `halt_on_trigger` | bool | 否 | `false` | `true` 时注入 `sdl -haltOnTrigger 1`（LA 模式下触发时同时停止仿真时钟，`xecmdref.pdf` P839） |
| `auto_probe` | bool | 否 | `false` | `true` 时注入 `sdl -auto on`（自动探针 SDL 中引用的信号与断言，`xecmdref.pdf` P859） |

```toml
# 日常极简用法（交由 user run_ice.tcl 控制或交互调试）
[sim]
tcl_file = '$EMU_ROOT/sim/run_ice.tcl'
opts = [
  '-fsdb',
]
```

```toml
# 批处理 + 托管离线波形采集 + 模板渲染 trigger.tdf 用法
[sim]
tcl_file = '$EMU_ROOT/sim/run_ice.tcl'
opts = ['-fsdb']
pm_mode = 'la'
run_cmd = 'run'
auto_exit = true

[sim.wave]
enable = true
mode = 'offline'
name = 'wave'
continuous_upload = true
time_unit = 'ns'
trigger_pos = 50
probe_scripts = [
  '$EMU_ROOT/sim/probes_clk.tcl',
  '$EMU_ROOT/sim/probes_cpu.tcl',
]
probes = [
  'probe -create -depth 2 tb_top.u_dut',
]

[sim.tdf]
name = 'trigger.tdf'
scope = 'tb_top.u_dut'
triggers = [
  'err_flag == 1',
]
halt_on_trigger = true

[sim.tdf.aliases]
err = 'err_valid && err_code != 0'
```

---

### 3.12 `[release]` — 发布打包配置

对应 `kemu release -db <db_name> --comdir <path> --type <tar|DB>`（`-db` 无需 `.toml` 后缀）。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `dest_dir` | string | **是**（跑 release 时） | - | 发布根目录（支持 `$EMU_ROOT` 展开或相对 `EMU_ROOT`） |
| `db_prefix` | string | 否 | `'database'` | 发布目录/tar 包前缀 |
| `include` | list[str] | **是**（跑 release 时） | `[]` | 需要打包/拷贝的必要目录、文件或脚本（相对于 `<comdir>/database/<database.name>/`） |
| `exclude` | list[str] | 否 | `[]` | 排除的通配符列表（如 `['*.tmp', '*.bak']`） |

**输出路径规则**（假设 `database.name = 'base'`，当前时间戳 `ts = yymmddhhmm`，如 `2607111221`）：
- `--type tar`：`<dest_dir>/<db_prefix>_<name>_<ts>.tar.gz`（例：`<dest_dir>/database_base_2607111221.tar.gz`）
- `--type DB`：`<dest_dir>/<db_prefix>_<name>_<ts>/`（例：`<dest_dir>/database_base_2607111221/`）

```toml
[release]
dest_dir = '$EMU_ROOT/release'
db_prefix = 'database'
include = [
  'xe_db',
  'import.qel',
  'precompile.qel',
  'compile.qel',
  'sim.csh',
]
exclude = [
  '*.tmp',
  '*.bak',
]
```

---

## 4. 校验规则（`db_config.py` 实现约束）

1. **按需校验与 `-db` 简写解析**：
   - CLI 参数 `-db <db_name>`（兼容 `--db`）自动将未带 `.toml` 后缀的名称补全为 `<db_name>.toml`；若已带 `.toml` 后缀则直接使用。
   - 公共必填项为 `[env].emu_root`；各命令仅按当前执行阶段校验所需 Section：
     - **ICE 前端（`analysis` / `elaborate` / `syn`）**：必填 `[netlist].name` 与 `[netlist].design_top`；无需填写 `[database]`、`[emulator]`、`[comp]`、`[sim]`、`[release]`。
     - **ICE 后端（`impt` / `precomp` / `comp`）**：必填 `[database].name`；定位网表按 `[database].netlist_dir` > `<comdir>/netlist/<[database].netlist or [netlist].name>/netlist_manifest.toml` > `[impt].netlist_files` 优先级解析，至少满足其一；存在 `netlist_manifest.toml` 时自动继承 `design_top` / `testbench_top`。
     - **IXCOM 日常单文件**：必填 `[database].name` 与 `[database].design_top`（若显式拆分 `[netlist]`，则按 `[netlist].design_top` 解析并在 `<comdir>/netlist/<netlist.name>/` 运行 `analysis`）。
2. **严格字段校验**：除自由键值表 `[env.vars]`、`[sim.tdf.aliases]` 与 `[emulator.machines]`（其 key 为满足 `[A-Za-z0-9_-]+` 的机器别名，value 为严格校验 `host`/`et3confg`/`target_system` 的表）外，任何 Section（包括 `[netlist]`、`[database]`、`[comp]`、`[[comp.symmetric]]`、`[sim]`、`[sim.wave]` 与 `[sim.tdf]`）检测到规范未定义的字段时直接报错并提示合法字段名，防止字段拼写错误静默失效。
3. **严格环境隔离与硬件配置校验**：
   - `[env].emu_root` 必须存在且为绝对路径（`/` 开头），并自动注入为 `EMU_ROOT` 供 `$EMU_ROOT` 展开。
   - 配置中所有 `$VAR` / `${VAR}` 引用**仅在 `[env].emu_root`（`EMU_ROOT`）与 `[env.vars]` 中解析**；遇到未定义的变量直接报错中止，**绝不读取外部 shell 环境变量**。
   - `[env.vars]` 中不可同时配置互斥变量 `XE_HOST` 与 `XE_HOST_FILE`（`emulator.pdf` P16）。
   - 执行 `elaborate` 时 `[netlist].platform`（或继承的 `[emulator].target_system`）以及执行后端/仿真（`impt` / `precomp` / `comp` / `ixcom` / `sim`）时的 `[emulator].target_system`（含单机覆写）仅允许 `'Z2'` / `'Z3'` / `'Z3_Lsystem'`；涉及硬件后端或仿真时，`[emulator].active` 必须非空且在 `[emulator.machines]` 中存在对应条目，且每台机器必须定义非空 `host`。
4. **`analysis` / `precomp` / `comp` / `ixcom` / `filelist` 校验**：
   - 执行 `analysis` 或 `syn` 时，`[[analysis.module]]` 至少配置 1 项；各 module 的 `name` 不可重复，且 `name` 与 `worklib` 必须满足 `[A-Za-z0-9_-]+`；每个 module 的 `verilog_filelist` 与 `vhdl_filelist` 至少非空一项；`define_list` 仅填写纯宏名或赋值（如 `'PALLADIUM'`、`'CLK_FREQ=100'`），不带 `+define+` 前缀（由模板自动拼接）。
   - `[filelist].replace` 每一项必须为长度为 2 的字符串列表 `[old_regex, new_str]`，且 `delete` / `replace` 中的正则语法合法。
   - `[comp].flow` 仅允许 `'unified'` / `'ppc'`；`[impt].mode` 仅允许 `'full'` / `'incr'`；`[ixcom].compile_mode` 仅允许 `'multi'` / `'single'`；`[ixcom].dump_mode` 仅允许 `'online'` / `'offline'`；`[sim].pm_mode` 仅允许 `''` / `'la'` / `'stb'` / `'vd'`；`[sim.wave].mode` 仅允许 `'offline'` / `'online'`，`trigger_pos` 须在 `0..100` 且 `num_files >= 0`；`[sim.tdf]` 中 `trigger_pos`（`0..100`）与 `post_trigger_samples`（`>= 0`）互斥、`acquire` 与 `no_acquire` 互斥（`SDL.pdf` P137, P139, P147, P149），且 `tdf_file` 与内联渲染字段（`scope`/`triggers`/`acquire`/`no_acquire`/`aliases`/`extra_lines`）互斥。
   - `[comp].symmetric_boards` 与 `[[comp.symmetric]]` 不可同时配置；在 `[[comp.symmetric]]` 单项中 `emulator`、`host` 与 `file` 三者互斥（至多指定其一；全省略时复用 `[emulator].active`），若填写 `emulator` 则必须在 `[emulator.machines]` 中存在，且 `advanced_placements` 仅允许在配置了 `boards` 时使用（`emulator.pdf` P28）。
5. **发布前检查**：`[release].include` 中的每一项在打包/拷贝前先检查是否存在，缺失时列出所有缺失项并中止，避免产出残缺发布包。

---

## 5. 完整示例

精简示例配置见：
- ICE 单文件一站式：[examples/ice_database.toml](./examples/ice_database.toml)
- ICE 双文件解耦：[examples/ice_netlist.toml](./examples/ice_netlist.toml) + [examples/ice_db_fv.toml](./examples/ice_db_fv.toml)
- IXCOM（SA）日常单文件：[examples/ixcom_database.toml](./examples/ixcom_database.toml)
