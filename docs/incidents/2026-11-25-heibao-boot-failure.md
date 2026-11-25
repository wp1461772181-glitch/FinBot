# 黑豹 X2 存储损坏后改启动参数，重启失联：现状与求助

写于 2026-11-25。写给帮忙排查的其他 AI 或工程师。所有时间均为北京时间（UTC+8）。

## 一句话

一台跑在黑豹 X2 上的服务器，系统盘（板载 eMMC）出现 ext4 目录损坏后，被内核切成只读。为了让 fsck 真正运行，我改了启动参数，让根分区以只读方式挂载，然后重启。从那次重启起，它就再也没有联网：WiFi、Tailscale、网线都连不上。现场没有显示器口，也没有接串口。需要找出最省事、最可靠的恢复办法。

## 设备

| 项目 | 情况 |
|---|---|
| 硬件 | 黑豹 X2（Panther X2），瑞芯微 RK3566，4 GB 内存 |
| 存储 | 板载 eMMC，29.1 GiB（内核识别为 `mmc0:0001 DF4032`），焊在板上不可拆 |
| 分区 | `/dev/mmcblk0p1` → `/boot`（ext4）；`/dev/mmcblk0p2` → `/`（ext4，约 14G 已用） |
| 系统 | Armbian（ophub 构建），内核 `6.18.41-ophub`，设备树 `rockchip/rk3566-panther-x2.dtb` |
| 引导 | U-Boot 读 `/boot/boot.scr`（源文件 `boot.cmd`），再导入 `/boot/armbianEnv.txt` |
| 外部接口 | 只有 USB、一个网口、一个 TF 卡槽。**没有 HDMI**，没有引出调试串口 |
| 平时联网 | 连家里 WiFi，通过 Tailscale 用 SSH 远程登录；几周来一直稳定 |
| 上面的服务 | FinBot（FastAPI）、Telegram/微信桥、哨兵；PostgreSQL 和 pgvector 跑在 Docker 里，数据目录 `/opt/finbot/postgres-data` 在根分区上 |

## 经过

### 1. 00:42 存储损坏，根分区变只读

内核日志：

```
EXT4-fs error (device mmcblk0p2): htree_dirblock_to_tree:1077: inode #294349: block 3348988:
  comm python: bad entry in directory: rec_len is smaller than minimal - offset=4004, inode=0, rec_len=0, size=4096 fake=0
Aborting journal on device mmcblk0p2-8.
EXT4-fs (mmcblk0p2): Remounting filesystem read-only
```

- 触发的是一次 Python 导入 pandas，坏的是 venv 里 `site-packages/pandas/core/computation/` 这个目录。
- `ls` 这个目录时，有一项显示为 `d?????????`，并报 `Structure needs cleaning`。另有一个文件名 `api.py` 变成了 `api.Py`，像是位翻转。所以损坏在 00:42 之前就已经存在。
- 后果：PostgreSQL 新连接报 `FATAL: could not open file "base/16384/2601": Read-only file system`，服务停摆。
- `tune2fs -l /dev/mmcblk0p2`：`Filesystem state: clean with errors`，`Last checked: Sat Aug 1 2026`。

### 2. 先保数据（已完成）

已复制到另一台 Mac，校验一致：

- 11-24 07:30 的夜间数据库备份：`finbot-…dump` 和 `pgvector-…dump`。
- 只读状态下整个 PostgreSQL 数据目录的 tar 拷贝（914M），包含 07:30 之后的数据。

所以最坏情况下，数据也能完整恢复。眼下要解决的是让这台机器重新起来。

### 3. 第一次重启：加 fsck 参数，能正常回来，但 fsck 没有跑

`/boot/armbianEnv.txt` 原文：

```
verbosity=7
bootlogo=true
fdtfile=rockchip/rk3566-panther-x2.dtb
rootdev=UUID=<根分区 UUID>
rootfstype=ext4
rootflags=rw,errors=remount-ro
earlycon=on
console=both
consoleargs=console=ttyS02,1500000 console=tty0
docker_optimizations=on
extraargs=rw rootwait
extraboardargs=net.ifnames=0 max_loop=128
overlay_prefix=rk3566
overlays=
user_overlays=
usbstoragequirks=0x2537:0x1066:u,0x2537:0x1068:u
```

- 原文件备份为 `/boot/armbianEnv.txt.before-fsck-20261125`。
- 改动：`extraargs=rw rootwait` 改成 `extraargs=rw rootwait fsck.mode=force fsck.repair=yes`。

重启后约 50 秒就回来了。但根分区仍以可写方式挂载，root 的 fsck 被跳过：

```
EXT4-fs (mmcblk0p2): warning: mounting fs with errors, running e2fsck is recommended
systemd-fsck-root.service - File System Check on Root Device skipped, unmet condition check ConditionPathIsReadWrite=!/
```

`/boot` 的 fsck 正常跑完，结果干净。

其他相关信息：

- `/etc/fstab` 的根分区行：`UUID=… / ext4 defaults,noatime,nodiratime,commit=600,errors=remount-ro 0 1`
- `boot.cmd` 先设默认值 `setenv rootflags "rw,errors=remount-ro"`，再导入 `armbianEnv.txt`，最后拼出：
  `setenv bootargs "root=${rootdev} rootwait rootfstype=${rootfstype} rootflags=${rootflags} ${consoleargs} consoleblank=0 loglevel=${verbosity} ubootpart=${partuuid} usb-storage.quirks=${usbstoragequirks} ${extraargs} ${extraboardargs}"`
- initramfs 是 `initramfs-tools`（`/boot/uInitrd`）。`/usr/share/initramfs-tools/hooks/` 里有 fsck 钩子，但用 `lsinitramfs` 查镜像时没有看到 fsck 或 e2fsck，所以不确定 initramfs 阶段会不会对根分区做 fsck。

### 4. 第二次重启：根分区改为只读挂载，此后失联

先停掉所有 FinBot 服务和两个 Docker 容器，然后改：

```
rootflags=ro,errors=remount-ro
extraargs=ro rootwait fsck.mode=force fsck.repair=yes
```

本意是：根分区只读挂载，让 `systemd-fsck-root` 用 `-y` 跑 e2fsck，完成后再由 `systemd-remount-fs` 按 fstab 切回可写。

重启后，它再也没有出现在 Tailscale 上：最后在线约 07:33，到写这份文档时已离线两个多小时。

### 5. 之后的尝试

| 尝试 | 结果 |
|---|---|
| 等待约 50 分钟 | 不上线 |
| 现场断电，10 秒后重新通电，指示灯亮 | 不上线 |
| 网线接家用路由器的 WAN/LAN1 口（这个口当前是 WAN 还是 LAN 不确定），在 Mac 上扫 `192.168.0.0/24` | 除 Mac 外没有任何主机开着 22 端口，也没有疑似黑豹的新设备 |
| 网线直连一台 Windows 笔记本，打开「Internet 连接共享」，笔记本网口地址为 `192.168.137.1`，并给黑豹断电重启 | `arp -a` 中 `192.168.137.1` 接口下只有广播和组播地址（`.255`、`224.*`、`239.*`），**黑豹没有来要地址** |

## 我的判断（需要复核）

黑豹平时靠 WiFi 加 Tailscale 上线，只要用户空间起来，不插网线也会上线。所以它多半停在了根分区 fsck 这一步，或者紧挨着它之前或之后：

1. **e2fsck 遇到 `-y` 也修不了的错误，或者 fsck 返回失败**，systemd 进入 emergency.target，在控制台等 root 密码。这时网络、sshd、Tailscale 都不会启动。我认为这种可能最大。
2. **e2fsck 修完后要求重启**（退出码表示文件系统已修改），重启后又被 `fsck.mode=force` 强制检查，存储如果还在持续出错，就会反复重启。
3. **存储读得很慢，fsck 跑了几个小时。** 已经过了很久，可能性较小。
4. **`ro` 被写了两遍**（`rootflags=ro` 和 `extraargs` 里的 `ro`），或者 `errors=remount-ro` 和只读挂载放在一起，导致后续切换可写失败、很多服务起不来。但 WiFi 和 Tailscale 也没起来，不太符合这种情况。

## 恢复思路

无论哪种可能，都需要在本机执行下面三步：

```
e2fsck -fy /dev/mmcblk0p2
cp /boot/armbianEnv.txt.before-fsck-20261125 /boot/armbianEnv.txt
reboot
```

注意：如果从 TF 卡启动，板载 eMMC 的设备名可能会变（比如变成 `mmcblk1`），要先用 `lsblk` 确认。

能进入本机的办法：

1. **TF 卡启动救援（目前首选）。** 用 ophub Armbian 的 `rk3566-panther-x2` 镜像写一张 TF 卡，插进去开机，然后从救援系统里对 eMMC 的根分区跑 e2fsck，并恢复 `/boot/armbianEnv.txt`。网上有「Panther X2 的 eMMC 损坏后用 TF 卡启动」的教程。不确定的地方是：eMMC 上的 U-Boot 还完好时，会不会优先从 TF 卡启动。
2. **USB 转 TTL 串口（CH340 等，1500000 波特率，3.3V）。** 要拆壳，接板上的调试焊点，具体位置待确认，可能需要焊接。接上后能直接进入 emergency shell。
3. **Maskrom 或 Loader 模式，用双公头 USB 线和 RKDevTool 线刷。** 会覆盖 eMMC，只在别的办法都不行时才考虑。

## 请帮忙确认

1. 按照上面的启动参数和 systemd 行为，最可能卡在哪一步？有没有我没想到的情况，比如 `ro` 写了两次、initramfs 阶段的 fsck 行为？
2. 在没有显示器和串口的情况下，有没有**不用拆壳**就能让它重新上线的办法？比如 U-Boot 阶段能否通过别的方式改启动参数，或者利用 TF 卡上的 `armbianEnv.txt` 或 `boot.scr`？
3. 黑豹 X2 在 eMMC 引导正常时，会不会优先从 TF 卡启动？如果不会，怎样让它从 TF 卡启动？
4. 恢复之后，这块 eMMC 还值得继续用吗？应该看哪些指标（比如 `mmc extcsd read` 的寿命字段、dmesg）来判断？

---

## 结果（11-25 16:50 已恢复）

**一句话：** 用 TF 卡救援系统修好了 eMMC、恢复了启动配置，黑豹从 eMMC 正常启动，Tailscale 上线，FinBot 全部服务健康，数据逐表核对，没有一张表比备份少。

### 怎么救回来的

1. 救援盘：闪迪 Ultra 32G TF 卡，写入 ophub `Armbian_26.11.0_rockchip_panther-x2_bookworm_6.18.63_server_2026.11.14.img.gz`（sha256 与发布页一致）。写卡前在 Mac 上用 e2fsprogs 的 `debugfs` 改镜像根分区：放入 root 登录公钥（700/600）、删掉 `/root/.not_logged_in_yet`（免首次登录交互）、加一个 NetworkManager 的 WiFi 配置（owner 在终端自己输入名称和密码，权限 600）。
2. 写卡：这台 Mac（macOS 27.2.1）认不出那个读卡器（USB `14cd:1212`，能枚举，但 U 盘驱动挂不上，换口也不行），手机能读。最后用安卓手机 + **EtchDroid**（开源，GitHub 发布页 v2.2，校验一致）写卡；镜像经手机热点下的局域网 HTTP 从 Mac 传到手机。
3. **插卡通电后，黑豹直接从 TF 卡启动**（eMMC 上的 U-Boot 会优先读卡，回答了上面第 3 问），连上手机热点，公钥登录成功。救援系统里 eMMC 是 `mmcblk0`，TF 卡是 `mmcblk1`。
4. 先只读检查（`e2fsck -fn`），经 owner 同意后 `e2fsck -fy /dev/mmcblk0p2`：回放日志，修正一个已删除 inode 的 dtime、块/inode 位图与计数、孤儿文件表；返回码 1（已修正），复查干净；`/boot` 分区本来就干净。**lost+found 为空，没有文件被挪走或删除。**
5. `/boot/armbianEnv.txt` 恢复为 `armbianEnv.txt.before-fsck-20261125`（逐字节一致）；改坏的那份留作 `armbianEnv.txt.broken-20261125-0734`。
6. eMMC 系统里原本就存着手机热点的连接，但 `autoconnect=false`。改为自动连接、优先级 -10（家里 WiFi 优先）。原文件备份在 eMMC `/root/nm-backup-20261125/`。这样黑豹不在家时也能经热点上 Tailscale。
7. 断电、拔卡、通电：从 eMMC 启动，约 1 分钟后 `ssh heibao-ts` 可连。根分区 rw 挂载，开机后 dmesg 里没有 EXT4/I/O 错误。

### 服务和数据

- 起服务前在救援系统里用 chroot 试导入：pandas 2.3.3 和 `app.main` 都正常，**venv 不需要重建**。
- 两个数据库容器（早上手动停掉的）启动正常，日志显示上次是 07:34 的正常关机，不需要崩溃恢复。
- 与 11-24 07:30 备份逐表比对（备份在 Mac 和盒上的校验一致）：65 张业务表里没有一张变少；增加的是 07:30 之后产生的对话、消息、新闻等（消息 8,890→8,956，新闻 7,118→8,599，对话 617→618，同意记录 61→62）；另有 4 张表是 07:30 之后建的新表。最新一条消息时间为 11-24 23:43（北京时间）。向量库 6,026 条。
- 服务顺序：先停 FinBot 服务 → 起数据库 → 起 `finbot-api`（`/health` ok）→ 起 rag-slim、telegram、wechat、sentinel，全部 active，起来后 warning 级别以上没有日志。公网 `公网 /health 地址` 返回 ok。
- 开机后夜间备份定时任务自动补跑成功（`*-20261125-085109.dump`），已拷到 Mac `~/FinBot-box-rescue-20261125/`，校验一致。

### 当初的"损坏"其实是什么

事后在盘上看，报错的目录 `pandas/core/computation`（inode 294349）**是完好的**：文件名正常（`api.py`，不是 `api.Py`），没有 `?????????` 项；fsck 的目录检查（Pass 2）也没报错。所以 00:42 那次更像是**一次读错**（eMMC 读出了错数据，或内存位翻转后写进了页缓存），而不是盘上的目录真坏了。内核看到坏数据后中止日志、改成只读，这一步是按设计保护数据。

失联的原因没能直接确认（失败那次的日志在 zram 里，断电后就没了）。最可能的情况仍然是：根分区只读挂载加强制 fsck，导致启动停在网络起来之前。

### 还有什么风险

1. **读错可能复发。** 原因没查明。eMMC（SanDisk DF4032，2017 年产）的寿命字段 `life_time=0x01 0x01`、`pre_eol_info=0x01`，属于磨损最低一档，不像是盘写坏了。之后要盯 dmesg 里的 EXT4 和 mmc 错误；如果再出，要考虑内存问题，或者把数据库挪到外接存储。
2. **备份目前只在盒上。** 每天自动同步到盒外还没设（等 owner 定），这次是手动拷了一份到 Mac。
3. **TF 救援盘交 owner 保管。** 里面有 root 公钥登录和手机热点的 WiFi 密码，不要外借。用法：断电 → 插卡 → 通电 → 在热点网段找开着 22 端口的设备 → 用公钥登录。救援系统只在本地网络可达。
4. 这台 Mac 不认那个读卡器，以后要重写救援盘还得走手机 EtchDroid。
