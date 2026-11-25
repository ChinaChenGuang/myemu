# KEMU `database.toml` 配置文件规范

本文档定义 `kemu` 所使用的 `database.toml` 配置文件结构、字段含义、必填规则及路径/环境变量约定。

---

## 1. 设计约定

1. **扁平直观**：直接按 Palladium 实际阶段划分 Section（`[database]`、`[env]`、`[lint]`、`[elab]`、`[impt]`、`[precomp]`、`[comp]`、`[sim]`、`[release]`），不做多层抽象嵌套。
2. **单文件自包含**：一个 `database.toml` 完整描述一个 database 的编译、仿真与发布参数，打开文件即可看全配置。
3. **环境变量规则**：
   - 字符串值中支持 `$VAR` / `${VAR}`（如 `$EMU_ROOT`）。
   - 渲染进 `xxx.sh` 的命令与路径默认**保留环境变量写法**（便于生成脚本可读、可迁移）；Python 侧做目录创建、文件拷贝/打包（如 `comdir`、`simdir`、`release.dest_dir`）时自动展开环境变量。
4. **LSF 覆盖规则**：
   - 全局可在 `[env].lsf_prefix` 中配置默认提交前缀（为空则本地 `bash` 直接执行）。
   - 任意阶段（`[lint]` / `[elab]` / `[impt]` / `[precomp]` / `[comp]` / `[sim]`）若单独设置了 `lsf_prefix`，则优先使用该阶段的配置（例如 `comp` 使用大内存队列，`lint` 使用普通队列）。
5. **逃生舱机制（`extra_lines`）**：
   - 每个涉及 `.qel` 或 `.sh` 渲染的阶段都保留 `extra_lines` 列表，方便随时追加临时命令或特殊选项，无需修改 Python 编排代码。

---

## 2. Section 与字段详细规范

### 2.1 `[database]` — Database 基础信息

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | **是** | - | Database 名称（如 `"min_system"`），用于日志标识及 `release` 目录/压缩包命名 |
| `top` | string | **是** | - | 顶层模块名（如 `"soc_top_tb"`） |
| `desc` | string | 否 | `""` | 简短描述，说明该 database 的用途 |

```toml
[database]
name = "min_system"
top = "soc_top_tb"
desc = "最小系统 ICE 编译与仿真配置"
```

---

### 2.2 `[env]` — 公共运行环境与调度配置

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `setup_scripts` | list[str] | 否 | `[]` | 每个 `xxx.sh` 开头依次 `source` 的环境脚本列表 |
| `vars` | table | 否 | `{}` | 需要在脚本开头 `export` 的环境变量键值对 |
| `lsf_prefix` | string | 否 | `""` | 全局默认作业提交前缀（如 `"bsub -Is -q emu"`）；留空表示本地直接 `bash` 执行 |

```toml
[env]
setup_scripts = [
  "$EMU_ROOT/env/setup_palladium.sh",
]
lsf_prefix = ""

[env.vars]
EMU_MODE = "ICE"
```

---

### 2.3 `[lint]` — 网表编译第一步（支持多线程并行）

对应 `kemu build ice --act lint`（以及 `--act syn` 的第一步）。  
`kemu` 会为 `[[lint.jobs]]` 中的每一项生成独立的 `lint_<name>.sh`，并使用 Python `ThreadPoolExecutor` 按 `max_workers` 并发执行。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `cmd` | string | 否 | `"hdlIce"` | lint 工具命令 |
| `max_workers` | int | 否 | `4` | 多线程并发数 |
| `lsf_prefix` | string | 否 | 继承 `[env]` | 覆盖全局 LSF 前缀 |
| `common_opts` | list[str] | 否 | `[]` | 所有 lint job 共享的公共选项 |
| `jobs` | list[table] | **是**（跑 lint/syn 时） | `[]` | 并行执行的 lint 子任务列表 |

`[[lint.jobs]]` 单项字段：

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `name` | string | **是** | - | 子任务名（决定生成脚本名 `lint_<name>.sh` 与日志名 `lint_<name>.log`） |
| `filelist` | string / list[str] | **是** | - | filelist 路径（单个字符串或列表） |
| `worklib` | string | 否 | 同 `name` | 编译目标库名 |
| `opts` | list[str] | 否 | `[]` | 该任务独有的选项，追加在 `common_opts` 之后 |

```toml
[lint]
cmd = "hdlIce"
max_workers = 4
common_opts = [
  "-sv",
  "+define+PALLADIUM",
]

[[lint.jobs]]
name = "sub_cpu"
filelist = "$EMU_ROOT/flist/sub_cpu.f"
opts = ["+define+CPU_MINI"]

[[lint.jobs]]
name = "sub_ddr"
filelist = "$EMU_ROOT/flist/sub_ddr.f"
opts = []
```

---

### 2.4 `[elab]` — 网表编译第二步

对应 `kemu build ice --act elab`（以及 `--act syn` 的第二步）。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `cmd` | string | 否 | `"hdlIce"` | elab 工具命令 |
| `top` | string | 否 | 继承 `[database].top` | 若 elab 顶层与 `[database].top` 不同可单独指定 |
| `lsf_prefix` | string | 否 | 继承 `[env]` | 覆盖全局 LSF 前缀 |
| `opts` | list[str] | 否 | `[]` | elab 命令行选项 |
| `extra_lines` | list[str] | 否 | `[]` | 追加到 `elab.sh` 中的自定义 shell 行 |

```toml
[elab]
cmd = "hdlIce"
opts = [
  "-elab",
  "-top", "soc_top_tb",
]
extra_lines = []
```

---

### 2.5 `[impt]` — 导入网表（`xeCompile import.qel`）

对应 `kemu build ice --act impt`。渲染 `import.qel` 与 `impt.sh` 并执行。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `cmd` | string | 否 | `"xeCompile"` | 导入命令 |
| `qel_file` | string | 否 | `"import.qel"` | 生成的 QEL 文件名（位于 `$EMU_ROOT/<comdir>/database/` 下） |
| `lsf_prefix` | string | 否 | 继承 `[env]` | 覆盖全局 LSF 前缀 |
| `opts` | list[str] | 否 | `[]` | 传给 `xeCompile` 的命令行参数 |
| `qel_lines` | list[str] | 否 | `[]` | 渲染到 `import.qel` 中的 QEL 语句列表 |

```toml
[impt]
cmd = "xeCompile"
qel_file = "import.qel"
opts = ["-l", "impt.log"]
qel_lines = [
  "config -top soc_top_tb",
  "import -format edif",
]
```

---

### 2.6 `[precomp]` — 预编译检查（`xeCompile precompile.qel`）

对应 `kemu build ice --act precomp`。渲染 `precompile.qel` 与 `precomp.sh` 并执行。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `cmd` | string | 否 | `"xeCompile"` | 预编译命令 |
| `qel_file` | string | 否 | `"precompile.qel"` | 生成的 QEL 文件名 |
| `lsf_prefix` | string | 否 | 继承 `[env]` | 覆盖全局 LSF 前缀 |
| `opts` | list[str] | 否 | `[]` | 传给 `xeCompile` 的命令行参数 |
| `qel_lines` | list[str] | 否 | `[]` | 渲染到 `precompile.qel` 中的 QEL 语句列表 |

```toml
[precomp]
cmd = "xeCompile"
qel_file = "precompile.qel"
opts = ["-l", "precomp.log"]
qel_lines = [
  "precompile -check",
]
```

---

### 2.7 `[comp]` — Database 最终编译

对应 `kemu build ice --act comp`。根据 `precomp` 的检查结果，通过 `params` 和 `qel_lines` 灵活调整编译参数，渲染 `compile.qel` 与 `comp.sh` 并执行。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `cmd` | string | 否 | `"xeCompile"` | 编译命令 |
| `qel_file` | string | 否 | `"compile.qel"` | 生成的 QEL 文件名 |
| `lsf_prefix` | string | 否 | 继承 `[env]` | 覆盖全局 LSF 前缀（通常 comp 需要大内存队列） |
| `opts` | list[str] | 否 | `[]` | 传给 `xeCompile` 的命令行参数 |
| `params` | table | 否 | `{}` | 根据 precomp 结果调整的结构化参数（供 `compile.qel.j2` 模板直接引用） |
| `qel_lines` | list[str] | 否 | `[]` | 渲染到 `compile.qel` 中的自定义/覆盖 QEL 语句 |

```toml
[comp]
cmd = "xeCompile"
qel_file = "compile.qel"
lsf_prefix = "bsub -Is -q emu_large"
opts = ["-l", "comp.log"]
qel_lines = [
  "compile -all",
]

[comp.params]
target_system = "Z2"
num_domains = 1
clock_freq = "10MHz"
```

---

### 2.8 `[sim]` — ICE 仿真配置

对应 `kemu sim ice --db <database.toml> --simdir <path> --session <name>`。  
CLI 传入的 `--simdir` 与 `--session` 会自动注入模板变量 `simdir` 和 `session`。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `cmd` | string | 否 | `"xeDebug"` | 仿真启动命令 |
| `lsf_prefix` | string | 否 | 继承 `[env]` | 覆盖全局 LSF 前缀 |
| `db_path` | string | 否 | `""` | database 路径（可选，若在仿真目录或环境变量中指定可留空） |
| `tcl_file` | string | 否 | `""` | 仿真运行脚本（如 `run.tcl`） |
| `opts` | list[str] | 否 | `[]` | 仿真启动参数 |
| `extra_lines` | list[str] | 否 | `[]` | 仿真脚本中追加的前置/后置 shell 命令 |

```toml
[sim]
cmd = "xeDebug"
db_path = "$EMU_ROOT/build/min_system/database"
tcl_file = "$EMU_ROOT/sim/run_ice.tcl"
opts = [
  "-nc",
]
extra_lines = []
```

---

### 2.9 `[release]` — 发布打包配置

对应 `kemu release --db <database.toml> --comdir <path> --type <tar|DB>`。

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `dest_dir` | string | **是**（跑 release 时） | - | 发布根目录（支持 `$EMU_ROOT` 等环境变量展开） |
| `db_prefix` | string | 否 | `"database"` | 发布目录/tar 包前缀 |
| `include` | list[str] | **是**（跑 release 时） | `[]` | 需要打包/拷贝的必要目录、文件或脚本（相对于 `$EMU_ROOT/<comdir>/database/`） |
| `exclude` | list[str] | 否 | `[]` | 排除的通配符列表（如 `["*.tmp", "*.bak"]`） |

**输出路径规则**（假设 `database.name = "min_system"`，当前时间戳 `ts = yymmddhhmm`，如 `2607111221`）：
- `--type tar`：
  `<dest_dir>/<db_prefix>_<name>_<ts>.tar.gz`  
  例：`<dest_dir>/database_min_system_2607111221.tar.gz`
- `--type DB`：
  `<dest_dir>/<db_prefix>_<name>_<ts>/<ts>/`  
  例：`<dest_dir>/database_min_system_2607111221/2607111221/`

```toml
[release]
dest_dir = "$EMU_ROOT/release"
db_prefix = "database"
include = [
  "xe_db",
  "import.qel",
  "compile.qel",
  "sim.sh",
]
exclude = [
  "*.tmp",
  "*.bak",
]
```

---

## 3. 校验规则（`db_config.py` 实现约束）

1. **按需校验**：执行 `build --act lint` 时不强制要求 `[release]` 或 `[sim]` 已填写，只校验公共必填项（`[database].name`、`[database].top`）及当前命令所需 Section 的必填项。
2. **错误提示明确**：缺少必填字段、TOML 语法错误、或 `$EMU_ROOT` 未设置时，直接打印缺失的字段路径（如 `缺少必填配置: [release].dest_dir`）并以非零状态退出，不抛晦涩的 Traceback。
3. **路径安全**：`[release].include` 中的每一项在打包/拷贝前先检查是否存在，缺失时给出清晰报错列表，避免产出残缺发布包。
