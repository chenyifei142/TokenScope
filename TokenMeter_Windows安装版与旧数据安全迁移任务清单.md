# TokenMeter Windows 安装版与旧数据安全迁移任务清单

> 当前项目：TokenMeter（原 TokenSpider）
> 目标平台：Windows 10 / Windows 11
> 目标：让普通用户只需下载一个安装包，选择安装目录后即可使用，并通过桌面快捷方式长期启动和更新。
> 核心要求：旧版 TokenSpider 用户的数据、配置、历史记录和凭据不得丢失。

---

# 一、最终用户体验

最终发布形式应为：

```text
TokenMeter-Setup-vX.Y.Z-x64.exe
```

用户操作流程：

```text
下载安装包
→ 双击运行
→ 选择安装目录
→ 安装程序文件
→ 自动创建桌面快捷方式
→ 启动 TokenMeter
→ 后续始终点击桌面快捷方式使用
→ 发现新版本后自动下载安装
→ 保留安装目录、快捷方式和用户数据
```

安装完成后的主程序固定名称：

```text
TokenMeter.exe
```

桌面快捷方式始终指向：

```text
安装目录\TokenMeter.exe
```

禁止让快捷方式指向带版本号的文件，例如：

```text
TokenMeter-v2.0.0.exe
```

---

# 二、执行原则

1. 遵循最小修改原则，不进行与安装版无关的重构。
2. 不允许直接删除或移动旧版数据。
3. 旧数据迁移必须采用：
   - 复制；
   - 验证；
   - 原子切换；
   - 保留旧目录备份。
4. 迁移失败时必须继续使用旧数据目录。
5. 安装器和自动更新不得覆盖或删除用户数据目录。
6. 敏感凭据继续使用 Windows Credential Manager，不改为明文文件。
7. 不修改当前版本号。
8. 不创建正式 GitHub Release。
9. 所有关键迁移路径必须补充测试。
10. Windows 安装和更新流程必须使用固定应用标识。

---

# 三、目标目录结构

## 3.1 默认安装目录

默认安装到：

```text
%LOCALAPPDATA%\Programs\TokenMeter
```

例如：

```text
C:\Users\<用户名>\AppData\Local\Programs\TokenMeter
```

允许用户在安装向导中选择其他目录，例如：

```text
D:\Apps\TokenMeter
```

不建议默认安装到：

```text
C:\Program Files\TokenMeter
```

原因是程序数据与自动更新需要写权限，普通用户通常不能直接修改 `Program Files`。

## 3.2 安装完成后的目录

```text
TokenMeter\
├─ TokenMeter.exe
├─ TokenMeterUpdater.exe
├─ _internal\
├─ assets\
└─ data\
   ├─ config.json
   ├─ usage.db
   ├─ widget-state.json
   ├─ logs\
   ├─ updates\
   ├─ browser-profile\
   └─ migration-state.json
```

注意：

- `data` 目录由程序首次启动时创建；
- PyInstaller 构建产物中不得打包真实用户数据；
- 安装器不得用模板文件覆盖已有 `data`；
- 自动更新不得删除 `data`。

---

# 四、PyInstaller 改为 onedir

## 涉及文件

至少检查：

- `TokenMeter.spec`
- `TokenMeterUpdater.spec`
- `scripts/build_release.py`
- `.github/workflows/release.yml`
- 相关测试

## 修改要求

主程序由单文件发布调整为目录发布：

```text
dist\
└─ TokenMeter\
   ├─ TokenMeter.exe
   ├─ TokenMeterUpdater.exe
   └─ _internal\
```

要求：

1. 使用 PyInstaller `onedir` 模式。
2. 主程序固定输出：
   ```text
   TokenMeter.exe
   ```
3. 更新器固定输出：
   ```text
   TokenMeterUpdater.exe
   ```
4. Qt、PySide6、pyqtgraph 等依赖放在 `_internal`。
5. 程序启动时工作目录不得依赖用户当前目录。
6. 所有资源路径使用：
   - `sys._MEIPASS`；
   - 可执行文件目录；
   - 或项目现有资源路径工具。
7. 不要把 `data` 目录打进构建产物。
8. 构建脚本应输出可供安装器打包的完整目录。

## 验收标准

执行：

```powershell
python scripts/build_release.py
```

后可以生成：

```text
dist\TokenMeter\TokenMeter.exe
dist\TokenMeter\TokenMeterUpdater.exe
dist\TokenMeter\_internal\
```

直接运行：

```powershell
dist\TokenMeter\TokenMeter.exe
```

应用可以正常启动、显示悬浮球、打开设置、读取数据和退出。

---

# 五、使用 Inno Setup 制作安装包

## 新增文件

```text
installer\TokenMeter.iss
```

## 安装包名称

```text
TokenMeter-Setup-v{version}-x64.exe
```

## 固定 AppId

创建一个固定 UUID，例如：

```ini
AppId={{6CF354B5-80AE-48BF-AFC5-890BDA5D8862}
```

重要：

- AppId 一旦发布后不得修改；
- 后续版本使用相同 AppId；
- 安装器才能识别旧版本并覆盖安装。

## 基础配置要求

安装器至少应支持：

- 简体中文；
- English；
- 日本語；
- 用户选择安装目录；
- 默认安装到 `%LOCALAPPDATA%\Programs\TokenMeter`；
- 无管理员权限安装；
- 创建桌面快捷方式；
- 创建开始菜单快捷方式；
- 创建卸载入口；
- 安装完成后可选择立即启动；
- 覆盖安装旧版本；
- 保留上一次安装目录；
- 安装期间关闭正在运行的 TokenMeter；
- 不删除用户数据。

## Inno Setup 参考结构

```ini
#define MyAppName "TokenMeter"
#define MyAppVersion "从 app_identity.py 或构建参数注入"
#define MyAppExeName "TokenMeter.exe"

[Setup]
AppId={{6CF354B5-80AE-48BF-AFC5-890BDA5D8862}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=zensoku142
AppPublisherURL=https://github.com/zensoku142/TokenMeter
AppSupportURL=https://github.com/zensoku142/TokenMeter/issues
AppUpdatesURL=https://github.com/zensoku142/TokenMeter/releases

DefaultDirName={localappdata}\Programs\TokenMeter
DefaultGroupName=TokenMeter
PrivilegesRequired=lowest
UsePreviousAppDir=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

OutputDir=..\dist-installer
OutputBaseFilename=TokenMeter-Setup-v{#MyAppVersion}-x64
SetupIconFile=..\assets\TokenMeter.ico
UninstallDisplayIcon={app}\TokenMeter.exe

Compression=lzma2
SolidCompression=yes
WizardStyle=modern

CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Tasks]
Name: "desktopicon"; \
    Description: "创建桌面快捷方式"; \
    GroupDescription: "附加任务："; \
    Flags: checkedonce

[Files]
Source: "..\dist\TokenMeter\*"; \
    DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userdesktop}\TokenMeter"; \
    Filename: "{app}\TokenMeter.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\TokenMeter.exe"; \
    Tasks: desktopicon

Name: "{group}\TokenMeter"; \
    Filename: "{app}\TokenMeter.exe"; \
    WorkingDir: "{app}"

Name: "{group}\卸载 TokenMeter"; \
    Filename: "{uninstallexe}"

[Run]
Filename: "{app}\TokenMeter.exe"; \
    Description: "启动 TokenMeter"; \
    Flags: nowait postinstall skipifsilent
```

需要根据实际构建结构调整，但不要改变整体目标。

---

# 六、桌面快捷方式要求

桌面快捷方式：

```text
名称：TokenMeter
目标：安装目录\TokenMeter.exe
起始位置：安装目录
图标：TokenMeter.exe 内置图标
```

要求：

1. 第一次安装时默认勾选创建桌面快捷方式。
2. 覆盖安装时不得重复生成多个快捷方式。
3. 后续升级不改变快捷方式目标。
4. 卸载程序时删除快捷方式。
5. 用户数据保留时，不影响快捷方式清理。

---

# 七、新数据目录策略

## 7.1 新安装用户

新用户直接使用：

```text
安装目录\data
```

不要再默认使用：

```text
%APPDATA%\TokenSpider
```

## 7.2 数据路径解析

新增统一数据目录解析逻辑，例如：

```python
def resolve_data_dir() -> Path:
    ...
```

优先级建议：

```text
1. 已完成迁移后的安装目录\data
2. 用户明确配置的数据目录
3. 可写的安装目录\data
4. 旧版 %APPDATA%\TokenSpider（迁移失败时兼容使用）
```

不得在多个模块中重复拼接数据目录。

## 7.3 安装目录可写性

程序启动时检查：

```text
安装目录\data
```

是否可创建和写入。

如果用户选择了无写权限目录：

1. 不得崩溃；
2. 不得静默丢数据；
3. 显示明确提示；
4. 可以回退到：
   ```text
   %LOCALAPPDATA%\TokenMeter\data
   ```
5. 在日志中记录实际数据目录。

---

# 八、旧 TokenSpider 数据安全迁移

## 8.1 旧目录

旧版数据通常位于：

```text
%APPDATA%\TokenSpider
```

可能包含：

```text
config.json
usage.db
widget-state.json
TokenSpider.log
logs\
updates\
browser-profile\
DeepSeek / MiMo 专用浏览器会话
location.json
migration-backup-*
```

## 8.2 迁移触发条件

首次启动安装版 TokenMeter 时：

```text
安装目录\data 不存在或为空
并且
%APPDATA%\TokenSpider 存在有效旧数据
```

才自动执行迁移。

以下情况不得自动覆盖：

- 新 `data` 已存在有效数据；
- 用户已明确选择其他数据目录；
- 旧目录为空；
- 迁移状态已经完成；
- 新目录存在来源不明的数据。

## 8.3 安全迁移流程

必须按照以下顺序执行：

```text
1. 解析旧数据目录
2. 解析新数据目录
3. 校验源目录和目标目录不是同一路径
4. 校验目标目录可写
5. 创建临时目录 data-migrating-<随机值>
6. 将旧数据复制到临时目录
7. 复制过程中不删除旧文件
8. 验证关键文件
9. 验证 SQLite 数据库可打开
10. 验证普通配置可解析
11. 原子重命名临时目录为 data
12. 写入 migration-state.json
13. 切换程序使用新目录
14. 保留旧目录不删除
```

禁止使用：

```python
shutil.move(...)
```

直接移动旧数据。

禁止在验证前删除：

```text
%APPDATA%\TokenSpider
```

## 8.4 关键文件验证

至少验证：

### config.json

- JSON 可以正常解析；
- 类型符合预期；
- 失败时不继续切换。

### usage.db

- SQLite 可以正常连接；
- 可以读取 Schema；
- 可执行简单查询；
- 不对旧数据库执行破坏性修改。

### widget-state.json

- 解析失败时可以忽略单个界面状态文件；
- 不应因此让全部数据迁移失败；
- 记录警告。

### 浏览器会话目录

- 复制失败时应明确记录；
- 不删除旧会话；
- 可以将其视为关键或非关键项，但行为必须明确并有测试。

## 8.5 迁移状态文件

新目录中写入：

```text
data\migration-state.json
```

参考内容：

```json
{
  "version": 1,
  "source": "%APPDATA%\\TokenSpider",
  "target": "D:\\Apps\\TokenMeter\\data",
  "completed": true,
  "completed_at": "ISO-8601 时间",
  "source_preserved": true
}
```

不要在状态文件中写入 Cookie、Token、API Key 或其他敏感信息。

## 8.6 迁移失败

发生以下情况时：

- 文件占用；
- 权限不足；
- 磁盘空间不足；
- JSON 损坏；
- SQLite 无法读取；
- 临时目录创建失败；
- 原子重命名失败；
- 程序被中断；

必须：

```text
1. 不切换到新目录
2. 不删除旧数据
3. 清理不完整的临时目录
4. 继续使用旧数据目录
5. 记录明确日志
6. 下次启动允许重新尝试
```

迁移失败不得阻止用户继续使用旧版本数据。

## 8.7 旧目录保留策略

迁移成功后：

```text
%APPDATA%\TokenSpider
```

暂时保留。

本任务中禁止自动删除旧目录。

至少在后续两个到三个版本中继续保留旧数据兼容。

可以在设置页显示：

```text
已从 TokenSpider 迁移数据。
旧数据目录仍保留，可确认无误后手动清理。
```

---

# 九、Windows Credential Manager 凭据兼容

当前敏感凭据可能使用：

```text
TokenSpider/
```

作为目标名前缀。

## 修复要求

1. 新版继续读取 `TokenSpider/` 旧凭据。
2. 可以增加 `TokenMeter/` 新前缀。
3. 读取优先级：
   ```text
   TokenMeter/ → TokenSpider/ → TokenScope/
   ```
4. 找到旧凭据后可以复制到新前缀。
5. 复制成功后暂时不删除旧凭据。
6. 凭据迁移失败时继续读取旧凭据。
7. 不得将敏感内容写入日志。
8. 不得将凭据保存到安装目录中的明文 JSON。

## 验收标准

旧用户升级后：

- DeepSeek Bearer Token 仍可读取；
- DeepSeek API Key 仍可读取；
- MiMo Cookie 仍可读取；
- 不需要重新登录；
- 不需要重新填写配置。

---

# 十、自动更新改为更新安装包

## 当前目标

不要再只替换单个：

```text
TokenMeter.exe
```

因为使用 `onedir` 后还需要更新：

```text
_internal\
依赖 DLL
Qt 插件
资源文件
TokenMeterUpdater.exe
```

## 新更新流程

```text
TokenMeter 检查 GitHub Release
→ 找到 TokenMeter-Setup-vX.Y.Z-x64.exe
→ 下载到 data\updates\vX.Y.Z\
→ 下载 SHA256SUMS.txt
→ 校验 SHA256
→ 验证数字签名（如果已经实现）
→ 启动安装包静默覆盖安装
→ 当前程序退出
→ 安装器使用原目录覆盖程序文件
→ 保留 data
→ 安装结束后重新启动 TokenMeter.exe
```

## 静默安装参数

建议：

```powershell
TokenMeter-Setup-vX.Y.Z-x64.exe `
  /VERYSILENT `
  /SUPPRESSMSGBOXES `
  /NORESTART `
  /CLOSEAPPLICATIONS
```

如果需要安装后自动启动，可使用安装器自定义参数，避免安装器和当前更新器重复启动程序。

## 自动更新要求

1. 更新程序只下载安装包和校验文件。
2. 安装包使用相同 AppId。
3. 安装包自动使用旧安装目录。
4. 更新不得重新询问安装路径。
5. 更新不得重新创建重复快捷方式。
6. 更新不得覆盖 `data`。
7. 更新完成后桌面快捷方式仍有效。
8. 更新失败时旧版本仍可启动。
9. 下载失败、校验失败和安装失败必须有明确错误提示。
10. 更新缓存只能位于数据目录的 `updates` 下。

---

# 十一、安装器对数据目录的保护

安装器 `[Files]` 只能安装程序文件。

不得包含：

```text
Source: "..\data\*"
```

不得配置自动删除：

```ini
[UninstallDelete]
Name: "{app}\data"; Type: filesandordirs
```

默认卸载行为：

```text
删除程序文件
删除快捷方式
保留 data
```

可以额外实现卸载询问：

```text
是否同时删除 TokenMeter 的配置、历史记录和浏览器会话？
```

默认选项必须是：

```text
不删除用户数据
```

只有用户主动选择时才删除 `data`。

---

# 十二、版本发布结构

GitHub Release 面向普通用户只展示：

```text
TokenMeter-Setup-vX.Y.Z-x64.exe
SHA256SUMS.txt
```

README 下载说明只引导下载：

```text
TokenMeter-Setup-vX.Y.Z-x64.exe
```

不再把以下内容作为普通用户入口：

```text
TokenMeter.exe
TokenMeterUpdater.exe
TokenMeter-vX.Y.Z-windows-x64.exe
TokenMeterUpdater-vX.Y.Z-windows-x64.exe
```

这些可以作为内部构建产物，但不应让普通用户自行组合。

---

# 十三、GitHub Actions 构建流程

建议流程：

```text
1. 安装 Python 依赖
2. 运行 pytest
3. 使用 PyInstaller 构建 onedir
4. 检查 TokenMeter.exe
5. 检查 TokenMeterUpdater.exe
6. 使用 Inno Setup 编译安装包
7. 安装包静默安装测试
8. 启动 TokenMeter.exe smoke test
9. 生成 SHA256SUMS.txt
10. 上传 GitHub Release
```

## Actions 中使用 Inno Setup

Windows runner 通常可安装或调用 Inno Setup 编译器。

构建命令参考：

```powershell
iscc installer\TokenMeter.iss
```

不得在测试失败时继续发布。

---

# 十四、必须补充的测试

## 14.1 数据目录解析

测试：

- 新安装目录可写；
- 安装目录不可写；
- 用户指定数据目录；
- 旧目录存在；
- 新目录已有数据；
- 路径相同；
- 路径包含中文和空格。

## 14.2 数据迁移

测试：

- 正常完整迁移；
- config.json 损坏；
- usage.db 损坏；
- widget-state.json 损坏；
- 复制中途失败；
- 目标目录创建失败；
- 原子重命名失败；
- 磁盘空间不足模拟；
- 文件占用；
- 临时目录残留；
- 重复启动迁移；
- 迁移成功后再次启动；
- 迁移失败后继续使用旧目录；
- 旧目录始终保留。

## 14.3 凭据兼容

测试：

- 优先读取 TokenMeter；
- 回退读取 TokenSpider；
- 回退读取 TokenScope；
- 旧凭据复制到新前缀；
- 复制失败后仍使用旧凭据；
- 日志不包含敏感内容。

## 14.4 更新流程

测试：

- 识别 Setup 安装包；
- 下载安装包；
- SHA256 校验；
- 安装参数正确；
- 安装目录保持不变；
- data 未被覆盖；
- 快捷方式目标保持不变；
- 更新失败后旧程序仍存在；
- 同一版本不重复安装。

## 14.5 安装器验证

至少进行人工或自动验证：

```text
全新安装
覆盖安装
自定义目录安装
中文目录安装
带空格目录安装
无管理员权限安装
桌面快捷方式启动
开始菜单启动
卸载后数据保留
重新安装后旧数据继续使用
```

---

# 十五、建议执行顺序

```text
1. 创建安装版专用分支
2. 实现统一数据目录解析
3. 实现 TokenSpider 旧数据安全迁移
4. 实现 Credential Manager 旧前缀兼容
5. 为迁移逻辑补充测试
6. 将 PyInstaller 改为 onedir
7. 新增 Inno Setup 脚本
8. 实现桌面与开始菜单快捷方式
9. 修改自动更新为下载安装包
10. 为自动更新补充测试
11. 修改 GitHub Actions
12. 修改 README 下载和安装说明
13. 执行 pytest
14. 构建 onedir
15. 编译安装包
16. 在干净 Windows 环境测试安装
17. 测试旧版数据升级
18. 输出迁移与构建报告
```

---

# 十六、README 需要同步说明

README 至少新增：

## 安装

```text
1. 下载 TokenMeter-Setup-vX.Y.Z-x64.exe
2. 双击运行安装程序
3. 选择安装目录
4. 安装完成后通过桌面快捷方式启动
```

## 数据位置

```text
新安装默认将数据保存在：
安装目录\data

从 TokenSpider 升级时，程序会安全复制旧数据。
旧目录不会被自动删除。
```

## 自动更新

```text
TokenMeter 会下载安装版更新，并覆盖程序文件。
用户数据和桌面快捷方式不会受到影响。
```

## 卸载

```text
默认卸载只删除程序，不删除用户数据。
```

---

# 十七、Codex 执行提示词

将本文件放在仓库根目录，然后发送：

```text
请读取仓库根目录的《TokenMeter_Windows安装版与旧数据安全迁移任务清单.md》，
并直接在当前 TokenMeter 仓库中实现标准 Windows 安装版。

目标：

1. 用户只需下载 TokenMeter-Setup-vX.Y.Z-x64.exe。
2. 安装时可以选择安装目录。
3. 自动创建桌面和开始菜单快捷方式。
4. 安装后的主程序固定为 TokenMeter.exe。
5. 新用户数据保存在 安装目录\data。
6. 旧 TokenSpider 用户的数据、配置、数据库和凭据不得丢失。
7. 后续更新通过下载安装包覆盖程序文件。
8. 更新和卸载默认不删除 data。

执行要求：

1. 先阅读现有 app_identity.py、config_manager.py、app_update.py、
   updater_main.py、PyInstaller spec、构建脚本、GitHub Actions 和测试。
2. 遵循最小修改原则，不进行无关重构。
3. 不允许直接移动或删除 %APPDATA%\TokenSpider。
4. 旧数据迁移必须使用：
   复制 → 验证 → 原子切换 → 保留旧目录。
5. 迁移失败时继续使用旧数据目录。
6. Windows Credential Manager 必须继续兼容 TokenSpider/ 和 TokenScope/。
7. 敏感凭据不得写入明文文件或日志。
8. PyInstaller 改为 onedir。
9. 使用 Inno Setup 生成安装包。
10. 使用固定 AppId，后续版本不得变化。
11. 桌面快捷方式始终指向 安装目录\TokenMeter.exe。
12. 自动更新改为下载 TokenMeter-Setup 安装包，并静默覆盖安装。
13. 安装器和更新器不得覆盖或删除 data。
14. 卸载默认保留用户数据。
15. 所有迁移、凭据兼容和更新路径补充测试。
16. 完成后运行：
    python -m pytest -q
17. 完成后构建：
    python scripts/build_release.py
18. 使用 Inno Setup 编译安装包。
19. 不修改当前版本号。
20. 不创建正式 Release。
21. 不推送代码，除非当前任务明确允许。
22. 最后输出：
    - 修改文件列表；
    - 新增文件列表；
    - 数据目录解析规则；
    - 旧数据迁移流程；
    - 凭据兼容策略；
    - 自动更新流程；
    - 新增测试；
    - pytest 完整结果；
    - PyInstaller 构建结果；
    - Inno Setup 构建结果；
    - 安装包路径；
    - 未完成事项；
    - 兼容性风险。

不要只给出建议或代码片段，请直接修改代码、添加测试并完成安装包构建。
```

---

# 十八、完成定义

只有同时满足以下条件，任务才算完成：

- 生成 `TokenMeter-Setup-vX.Y.Z-x64.exe`；
- 用户可选择安装目录；
- 默认安装不需要管理员权限；
- 桌面快捷方式可以正常启动；
- 开始菜单入口可以正常启动；
- 主程序固定为 `TokenMeter.exe`；
- 新用户数据保存到 `安装目录\data`；
- 旧 `%APPDATA%\TokenSpider` 数据可以安全迁移；
- 迁移失败时仍能继续使用旧数据；
- 旧目录不会被自动删除；
- Windows 凭据继续可用；
- 更新通过安装包完成；
- 更新后快捷方式仍有效；
- 更新不会覆盖或删除 data；
- 卸载默认保留用户数据；
- 全部测试通过；
- onedir 构建通过；
- Inno Setup 安装包构建通过；
- 在干净 Windows 环境完成安装、升级和卸载验证。
