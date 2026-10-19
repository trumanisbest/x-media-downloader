## X 媒体下载器 v1.1.0（Windows 桌面版）

macOS 风格侧边栏分栏界面的 X / Twitter 图片与视频下载器，开箱即用，**不需要安装 Python**。

### 下载安装

**方式一：安装版（推荐）**

下载 `XMediaDownloader-Setup-v1.1.0.exe` → 双击安装 → 向导全中文 → 默认装到
`%LOCALAPPDATA%\Programs\XMediaDownloader`，**不需要管理员权限**。
勾选「创建桌面快捷方式」，装完桌面就有图标。

卸载：控制面板 → 「X 媒体下载器」。卸载会清理程序文件、快捷方式与注册表项，
但保留你的配置与已下载内容，重装后设置还在。

静默安装（企业批量部署）：

```bash
XMediaDownloader-Setup-v1.1.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
```

**方式二：绿色版（免安装）**

下载 `XMediaDownloader-v1.1.0-windows-x64.zip` → 解压到任意文件夹 → 双击 `XMediaDownloader.exe`。
必须整个文件夹一起解压，`gdl.exe` 与 `_internal/` 不能丢；换位置后请重建快捷方式。

### 使用前必读：设置 Cookies

X 不登录抓不到任何内容（日志会提示 `AuthRequired`）：

1. 浏览器装扩展 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)
2. 打开 x.com 并登录
3. 点扩展图标 → Export，得到 `cookies.txt`
4. 程序内「高级设置」→ Cookies 文件 → 选中它

> Chrome 新版对 cookie 加了 app-bound 加密，「从浏览器读取」可能失败（日志出现 `Failed to decrypt cookie (DPAPI)`），请用上面的扩展导出方式。

### 功能

- 多个账号批量下载（逗号或空格分隔），自动按账号名建子目录
- 仅图片 / 仅视频 / 图片与视频；时间范围支持全部 / 最近 N 天 / 自定义
- **代理自动检测**：自动扫描本机 Clash 端口、系统代理、环境变量、直连，无需手填地址
- 断点续传、下载前预扫描显示 `x/N` 进度条、实时分级日志
- 环境自检（引擎版本 / cookies / 目录可写 / 网络连通性）
- 支持 cookies、限速、数量上限、保存推文 json

### 目录说明

```
XMediaDownloader.exe   主程序（无黑框）
gdl.exe                内置下载引擎（后台子进程，不要删）
_internal/             运行库（不要删）
使用说明.txt / app.ico
```

卸载：删除整个文件夹即可，不写注册表。配置保存在 `%APPDATA%\XMediaDownloader\`。

### 源码运行

```bash
pip install gallery-dl        # Python 3.8+，需带 tkinter
python x_media_downloader.py
```

底层引擎：[gallery-dl](https://github.com/mikf/gallery-dl)。仅供个人学习研究使用。
