# EchoVault Premium (ASMR.one 专版下载器)

![EchoVault Premium UI](https://github.com/user-attachments/assets/placeholder) <!-- 可以后续自己截图替换 -->

基于 Python 和 Flet 构建的一款现代化、高性能、高颜值的 ASMR.one 专用下载工具。
彻底抛弃了简陋的命令行与脆弱的历史记录系统，采用全新重构的底层网络架构，专为需要批量下载、管理巨量音声资源的用户打造。

## ✨ 核心特性 / Features

### 🎨 极致的现代化 UI
- 基于 **Flet (Flutter for Python)** 构建，丝滑的 60fps 动画交互。
- 精心调教的暗色系 **毛玻璃拟物风 (Glassmorphism)**，充满未来感与高级感。
- 任务卡片实时展示详细进度条、下载网速、单轨进度弹窗。

### 🚀 智能网络分流 (极其省流量！)
- **解决痛点**：由于 ASMR.one 官网被墙，获取元数据必须挂梯子；但其底层的语音存储服务器其实可以在国内直连且速度极快。
- **独家机制**：本程序内置**智能路由分离**，获取封面、简介、目录时**自动走您的代理（梯子）**，而在真正开始下载动辄几十 GB 的音频正片时，**自动切换为直连高速 CDN**！
- 彻底帮您省下宝贵的梯子流量！当然，您也可以在设置中开启“下载时也使用代理”。

### ⚡ 完美的断点续传与队列管理
- **任务防丢**：无论塞进去几百个 RJ 号，全量记录在 `queue.json` 中，哪怕中途断电关机，下次打开自动复原队列。
- **断点续传**：底层采用 HTTP `Range` 分块读取技术，精确到字节级别的续传，再也不怕网络抖动导致大文件从头重下。
- **暂停 / 取消**：随时随地一键暂停/恢复任务，一键清理历史记录。完成的任务会在下次重启时自动清理出队列，保持界面清爽。

### 🎵 全自动音频打标 (Auto Tagging)
- 下载完成后，系统会自动利用拉取的元数据（封面、标题、声优 CV、社团等），为您的 `.mp3`, `.flac`, `.ogg` 文件**自动写入音频标签（ID3 Tags）**。
- 导入任何手机或播放器，都会直接显示精美的专辑封面和作者信息！

### 📦 批量导入与自动防重
- 支持一键导入充满 RJ 号的 `.txt` 文本，正则引擎会自动精准提取里面所有的 RJ 码。
- 智能识别资源库中已存在的文件，遇到已经存在的音轨瞬间秒过，不浪费一丝网络和磁盘寿命。

## 🛠️ 安装与运行

### 1. 环境依赖
请确保您的电脑上已安装 **Python 3.10** 或更高版本。

### 2. 获取代码
```bash
git clone https://github.com/5788324/arsm-downing.git
cd arsm-downing
```

### 3. 安装所需库
项目根目录下运行：
```bash
pip install -r requirements.txt
```
*(如果缺失 `requirements.txt`，请确保安装以下核心库: `flet`, `aiohttp`, `aiofiles`, `mutagen`, `colorama`)*

### 4. 启动程序
```bash
python main.py
```

## ⚙️ 设置与使用指南

1. **配置代理**：第一次打开后，请前往【设置】页面，填入您的梯子本地端口（例如 `http://127.0.0.1:7890`）。
2. **下载路径**：在设置中选择您想保存音频的文件夹（默认在程序根目录的 `dist/Downloads` 下）。
3. **开始下载**：在【下载中心】的输入框里粘贴任意包含 RJ 号的文字，或者直接点击【批量导入文件】选择 txt 文本。点击【下载】即可让它在后台默默为您工作！

## 📄 免责声明
本程序仅作为学习 Python 异步编程及 Flet UI 框架的技术交流产物。请尊重原作者版权，请勿用于任何商业或非法传播用途。

## 📝 License

Based on [takoyune/asmr.one-downloader](https://github.com/takoyune/asmr.one-downloader), MIT License.

Original author: Takoyune. Modified by: 5788324.

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
