# KEMU 项目开发计划

## 1. 项目定位与开发原则

`kemu` 是基于 Python 的 Palladium（ICE）编译、仿真与发布脚本编排工具，核心链路为：

```text
CLI 参数 + database.toml -> Python 解析 -> Jinja2 渲染 xxx.sh / xxx.qel -> 执行（支持多线程 / 可选 LSF）
```

**开发原则**：
1. **避免过度开发**：不引入复杂框架、抽象工厂或多余设计模式，直接面向 Palladium 流程编写。
2. **简单易懂**：脚本和模板直观可读，工程师能直接看懂生成的 `.sh` / `.qel` 并方便微调。
3. **命名贴合实际项目**：模块、函数和配置字段均使用 Palladium / Emulation 真实术语（`ice`、`lint`、`elab`、`syn`、`impt`、`precomp`、`comp`、`sim`、`release`、`comdir`、`simdir`、`session`）。

---

## 2. 技术选型与运行约束

- **Python 版本**：Python 3.11+（使用标准库 `tomllib` 解析 TOML，使用 `concurrent.futures.ThreadPoolExecutor` 实现多线程调度，使用 `argparse` 解析命令行）。
- **外部依赖**：仅 `jinja2`。
- **执行模式**：
  - 默认生成 `xxx.sh`（及必要的 `.qel`）并立即执行。
  - 提供 `--gen-only` 选项：仅渲染脚本文件，不实际执行，便于检查或手动提交。
- **调度方式**：默认本地 `bash xxx.sh` 执行；支持在 `database.toml` 中可选配置集群提交前缀（如 `bsub ...`）。

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
│   ├── render.py            # Jinja2 模板加载与渲染，生成可执行 xxx.sh / xxx.qel
│   ├── runner.py            # 脚本执行与日志落盘，支持多线程并发（lint 阶段）与可选 bsub 前缀
│   ├── build_ice.py         # build ice：lint / elab / syn / impt / precomp / comp
│   ├── sim_ice.py           # sim ice：仿真脚本生成、session 绑定与日志归集
│   └── release.py           # release：tar 打包与 DB 时间戳目录发布
├── templates/               # Jinja2 脚本模板
│   ├── ice_lint.sh.j2       # 单任务 lint 脚本模板
│   ├── ice_elab.sh.j2       # elab 脚本模板
│   ├── ice_impt.sh.j2       # impt 启动脚本（调用 xeCompile import.qel）
│   ├── import.qel.j2        # import.qel 模板
│   ├── ice_precomp.sh.j2    # precomp 启动脚本（调用 xeCompile precompile.qel）
│   ├── precompile.qel.j2    # precompile.qel 模板
│   ├── ice_comp.sh.j2       # comp 启动脚本（调用 xeCompile compile.qel）
│   ├── compile.qel.j2       # compile.qel 模板（支持根据 precomp 结果调整参数）
│   └── ice_sim.sh.j2        # sim ice 启动脚本
├── examples/
│   └── database.toml        # 完整示例配置（含中文注释）
└── tests/                   # 单元测试（不依赖真实 Palladium 环境即可运行）
```

---

## 4. 命令与功能规划

### 4.1 `kemu help`
- 输出各子命令（`build` / `sim` / `release`）的用法说明与典型使用示例。

### 4.2 `kemu build`
- `kemu build ice --db <database.toml> --comdir <path> --act <action> [--gen-only]`
  - **工作目录**：`$EMU_ROOT/<path>/database/`（若目录不存在则自动创建；若未设置 `$EMU_ROOT` 给出清晰报错）。
  - **所有生成的脚本、`.qel`、log 与 database 文件均落在该工作目录下执行与保存**。
  - **`--act` 支持的动作**：
    - `lint`：读取 `[lint]` 中的任务列表，通过 Python 多线程并发渲染并执行各模块的 lint 脚本（可配置并发线程数 `max_workers`）。
    - `elab`：渲染并执行 elab 脚本，完成网表创建。
    - `syn`：顺序执行 `lint` -> `elab`（任一步失败即中止）。
    - `impt`：渲染 `import.qel` 与 `ice_impt.sh`，执行 `xeCompile import.qel`。
    - `precomp`：渲染 `precompile.qel` 与 `ice_precomp.sh`，执行 `xeCompile precompile.qel`。
    - `comp`：渲染 `compile.qel` 与 `ice_comp.sh`，支持读取 `[comp]` 中基于 precomp 结果调整后的参数，执行最终 database 编译。
- `kemu build ixcom ...`
  - 明确输出提示：`ixcom 暂不支持` 并返回非零退出码。

### 4.3 `kemu sim`
- `kemu sim ice --db <database.toml> --simdir <path> --session <session_name> [--gen-only]`
  - `--simdir`：仿真日志归集目录（不存在则自动创建）。
  - `--session`：指定 Palladium 仿真 session 名称，传入模板渲染到 `ice_sim.sh`。
- `kemu sim ixcom ...`
  - 明确输出提示：`ixcom 暂不支持` 并返回非零退出码。

### 4.4 `kemu release`
- `kemu release --db <database.toml> --comdir <path> --type <tar|DB>`
  - 根据 `[release]` 配置的必要目录/文件/脚本清单，从 `$EMU_ROOT/<comdir>/database/` 收集目标内容。
  - `--type tar`：打包为 `.tar.gz`（或 `.tar`）发布包到配置的发布目录。
  - `--type DB`：拷贝到对应发布目录下，按独立时间戳建目录，如：
    `database_<db_name>_<yymmddhhmm>/<yymmddhhmm>/`（具体命名规则可在 `database.toml` 中配置前缀）。

---

## 5. `database.toml` 配置结构草案

```toml
[database]
name = "min_system"                 # database 名称，用于日志和 release 目录命名
top_module = "top_tb"               # 顶层模块名

[run]
lsf_prefix = ""                     # 可选，如 "bsub -Is -q emu"；留空则本地 bash 执行
env_setup = []                      # 可选，脚本开头 source 的环境脚本列表

[lint]
max_workers = 4                     # lint 阶段多线程并发数
cmd = "hdlIce"                      # lint 命令（可按项目实际工具修改）
common_opts = []
# 每个子项为一个独立 lint 任务，多线程并行执行
[[lint.jobs]]
name = "sub_a"
filelist = "flist/sub_a.f"
opts = []

[elab]
cmd = "hdlIce"
opts = []

[impt]
cmd = "xeCompile"
qel_file = "import.qel"
opts = []

[precomp]
cmd = "xeCompile"
qel_file = "precompile.qel"
opts = []

[comp]
cmd = "xeCompile"
qel_file = "compile.qel"
# 根据 precomp 结果灵活调整的参数（直接渲染进 compile.qel）
extra_qel_lines = []
opts = []

[sim]
cmd = "xeDebug"
opts = []

[release]
dest_dir = "./releases"             # 发布根目录（支持环境变量展开）
include_items = [                   # 需要打包/拷贝的必要目录、文件或脚本
  "xe_db",
  "run_sim.sh",
]
```

---

## 6. 分阶段开发与验证里程碑

| 阶段 | 任务 | 验证方式 |
|---|---|---|
| **M1** | 搭建项目骨架、`cli.py`（`help` / `build` / `sim` / `release` + `ixcom` 拦截）与 `db_config.py` | 运行 `kemu help`、测试配置解析与缺失 `$EMU_ROOT` / 字段校验 |
| **M2** | 实现 `render.py`（Jinja2 模板渲染）与 `runner.py`（本地执行、LSF 前缀、日志落盘、多线程调度） | 用 mock 命令验证并发执行、失败捕获、日志输出与 `--gen-only` 模式 |
| **M3** | 实现 `build_ice.py` 与 `lint/elab/syn/impt/precomp/comp` 模板 | 在临时 `$EMU_ROOT` 下跑通全部 6 个 `--act` 动作并检查生成脚本与目录结构 |
| **M4** | 实现 `sim_ice.py` 与 `ice_sim.sh.j2` 模板 | 验证 `--simdir` 日志归集、`--session` 注入与脚本生成 |
| **M5** | 实现 `release.py`（`tar` 与 `DB` 两种模式） | 验证 tar 包内容完整性、DB 时间戳目录结构与文件拷贝 |
| **M6** | 编写完整单元测试 `tests/` 与精简 `README.md` | 运行 `pytest` / `unittest` 全量通过 |
