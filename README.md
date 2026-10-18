# X (Twitter) 媒体下载器 · 桌面版

带图形界面的 X / Twitter 博主图片与视频下载工具。**开箱即用的 Windows 桌面程序**（PyInstaller 打包，无需安装 Python）。

## 界面

macOS 风格侧边栏分栏布局：

| 页面 | 内容 |
| --- | --- |
| 下载 | 博主账号、下载类型（仅图片 / 仅视频 / 图片与视频）、时间范围、保存目录 |
| 高级设置 | cookies、代理自动检测、下载间隔、数量上限、断点续传、保存推文 json |
| 运行日志 | 带时间戳与分级着色的实时日志，自动跳到该页 |
| 已下载 | 按账号统计文件数与体积 |
| 帮助 | cookies 获取、代理检测、常见错误排查 |

## 功能

- 支持多个账号（逗号或空格分隔），自动按账号名建子目录
- 时间范围：全部 / 最近 N 天 / 自定义起止日期（含当天）
- **代理自动检测**：自动扫描本机 Clash 端口（7890 / 7897 / 10809 …）、Windows 系统代理、环境变量、直连，无需手填
- 断点续传（gallery-dl archive），中断后重跑自动跳过已下载
- 下载前预扫描，日志显示 `x/N` 进度与真实进度条
- 环境自检：Python / 引擎版本 / cookies 文件 / 目录可写 / 网络连通性
- 日志同时写入 `保存目录/download.log`

底层引擎：[gallery-dl](https://github.com/mikf/gallery-dl)（桌面版已内置）。

## 使用

1. **设 cookies**（必须）：X 不登录抓不到内容。
   装浏览器扩展 [Get cookies.txt LOCALLY](https://chromewebstore.google.com/) → 登录 x.com → 导出 `cookies.txt` → 在「高级设置」里选中它。
   > Chrome 新版对 cookie 加了 app-bound 加密，「从浏览器读取」可能失败（日志出现 `Failed to decrypt cookie (DPAPI)`），请用上面的扩展导出方式。
2. 填账号 → 选类型与时间范围 → 选保存文件夹 → 点「开始下载」。
3. 代理会自动探测；若失败再手动填，例如 `http://127.0.0.1:7897`。

## 运行方式

### 桌面版（推荐）

下载 Release 里的 `XMediaDownloader` 压缩包，解压后双击 `XMediaDownloader.exe`。

目录说明：

```
XMediaDownloader.exe   主程序（无黑框）
gdl.exe                内置下载引擎（后台子进程）
_internal/             运行库
app.ico                程序图标
```

卸载：删除整个文件夹 + 快捷方式即可，不写注册表。配置在
`%APPDATA%\XMediaDownloader\.x_downloader_config.json`。

### 源码运行

```bash
pip install gallery-dl     # Python 3.8+，需带 tkinter
python x_media_downloader.py
```

Windows 也可直接双击 `启动下载器.bat`（自动检测 Python / tkinter 并安装 gallery-dl）。

## 自行打包 exe

```bash
pip install pyinstaller pillow gallery-dl
python build/make_icon.py                      # 生成 build/app.ico
pyinstaller build/XMediaDownloader.spec --noconfirm --distpath dist --workpath build/_work
```

产物在 `dist/XMediaDownloader/`。注意：

- `gdl.exe` 必须是 **console 子系统**（GUI 子系统下 `sys.stdout` 为 None，读不到日志），主程序用 `STARTF_USESHOWWINDOW` 隐藏其窗口
- gallery-dl 的 extractor / downloader 是动态导入，靠 `build/hook-gallery_dl.py` 收集子模块，否则 twitter 提取器会缺失
- spec 里的路径相对 spec 所在目录，脚本中用 `SPECPATH` 拼绝对路径

## 免责声明

仅供个人学习研究使用，请遵守 X 的服务条款与当地法律法规，勿用于商业或侵权用途。
