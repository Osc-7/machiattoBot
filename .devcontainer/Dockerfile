# 显式指定平台
FROM --platform=linux/arm64 ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /work

# 1. 换清华源 (Ubuntu 22.04)
RUN sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.tuna.tsinghua.edu.cn/ubuntu/|g' /etc/apt/sources.list \
    && sed -i 's|http://security.ubuntu.com/ubuntu/|http://mirrors.tuna.tsinghua.edu.cn/ubuntu/|g' /etc/apt/sources.list \
    && sed -i 's|http://ports.ubuntu.com/ubuntu-ports/|http://mirrors.tuna.tsinghua.edu.cn/ubuntu-ports/|g' /etc/apt/sources.list

# 2. 安装基础工具
RUN apt-get update && apt-get install -y \
    bash git curl wget ca-certificates build-essential sudo \
    python3 python3-pip ripgrep \
    && rm -rf /var/lib/apt/lists/*

# 3. Python pip 清华源
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir numpy pandas matplotlib requests rich

# 4. 创建 arm64 兼容普通用户
ARG USERNAME=claudeuser
ARG USER_UID=1000
ARG USER_GID=1000

RUN groupadd --gid $USER_GID $USERNAME || true \
    && useradd --uid $USER_UID --gid $USER_GID -m $USERNAME -s /bin/bash || true \
    && echo "$USERNAME ALL=(root) NOPASSWD:ALL" > /etc/sudoers.d/$USERNAME \
    && chmod 0440 /etc/sudoers.d/$USERNAME
WORKDIR /work
COPY . /work

# 5. 安装 Node.js 18 LTS (arm64) 和 npm，安装 Claude Code CLI 及其依赖
USER claudeuser
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash - \
    && sudo apt-get install -y nodejs \
    && sudo npm install -g @anthropic-ai/claude-code 

# 保持 root 身份结束，不要写 USER claudeuser