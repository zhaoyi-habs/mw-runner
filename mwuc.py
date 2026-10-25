#!/usr/bin/env python3
"""
迷你世界 · 云模拟器控制器

针对 yuanqi-cloud-android.yml 失败日志的三处修正：
  1. AVD 放 /mnt（约 65G），不放只有 4.6G 的 /home/runner
  2. 安装真·迷你世界 APK（1.69G），不是 apk-game 里 120KB 的测试包
  3. 下载带校验和重试，杜绝 120158 字节这种残缺文件
"""
import os, json, time, base64, subprocess, urllib.request, urllib.error, re, traceback

TOKEN = os.environ["GH_TOKEN"]
REPO  = os.environ["GITHUB_REPOSITORY"]
HOME  = os.path.expanduser("~")
SDK   = os.environ.get("ANDROID_SDK_ROOT", "/usr/local/lib/android/sdk")
ADB   = SDK + "/platform-tools/adb"
EMU   = SDK + "/emulator/emulator"

PKG = "com.minitech.miniworld.uc"   # 九游版
ACT = None   # 用 monkey 启动，不猜 Activity 名
APK_URL = ("https://downali.9game.cn/s1/5/1/2026092111021541_com.minitech.miniworld.uc.apk"
           "?x-oss-process=udf/uc-apk,ZBHDgDZ0KFphAsOP8798b5952f437b6f"
           "&did=f84ac0ab-1095-44de-aeba-99a0bdb6f387")
APK_MD5 = ""   # 九游包不校验 MD5
APK_MIN   = 1_700_000_000        # 1.69G，低于这个数就是废文件
QQ_URL    = "https://d.apkpure.net/b/APK/com.tencent.mobileqq?version=latest"
QQ_PKG    = "com.tencent.mobileqq"
QQ_MIN    = 100_000_000

AVD_ROOT = os.environ.get("ANDROID_AVD_HOME", "/mnt/avd")
AVD      = "mwuc"
WORK     = "/mnt/mw"
APK      = WORK + "/mw.apk"

CMD  = "relay/mw_cmd.txt"
RES  = "relay/mw_res.txt"
DEADLINE = time.time() + 5.2 * 3600
_chunk = 180_000

# ───────────────────── GitHub 中转
def api(path, method="GET", data=None, ref="apk-build"):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    if method == "GET":
        url += f"?ref={ref}"
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", "Bearer " + TOKEN)
    req.add_header("User-Agent", "mwctl")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, json.dumps(data).encode() if data is not None else None, timeout=50) as r:
            raw = r.read().decode("utf-8", "replace")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        if e.code in (404, 304):
            return None
        raise

_SHA = {}
def put(path, content):
    for attempt in range(4):
        try:
            body = {"message": "ctl " + path,
                    "content": base64.b64encode(content.encode()).decode(),
                    "branch": "apk-build"}
            sha = _SHA.get(path)
            if sha is None or attempt:
                old = api(path)
                sha = old.get("sha") if old else None
            if sha:
                body["sha"] = sha
            r = api(path, "PUT", body)
            if isinstance(r, dict) and r.get("content", {}).get("sha"):
                _SHA[path] = r["content"]["sha"]
            return True
        except Exception:
            _SHA.pop(path, None)
            time.sleep(0.6)
    return False

def get(path):
    try:
        j = api(path)
        return base64.b64decode(j["content"]).decode("utf-8", "replace") if j and "content" in j else None
    except Exception:
        return None

# ───────────────────── shell
def sh(c, t=180, binary=False):
    try:
        p = subprocess.run(c, shell=True, capture_output=True, text=not binary, timeout=t)
        return p.stdout if binary else ((p.stdout or "") + (p.stderr or ""))
    except subprocess.TimeoutExpired:
        return b"" if binary else "TIMEOUT"

def adb(*a, t=180):
    return sh(" ".join([ADB, *map(str, a)]), t).strip()

_buf = []
def L(s):
    line = time.strftime("%H:%M:%S") + " " + str(s)[:1200]
    _buf.append(line)
    print(line, flush=True)
    put("relay/mw_log.txt", "\n".join(_buf[-140:]))

def pkg_installed(pkg):
    return pkg in adb("shell", "pm", "list", "packages", t=120)

def force_start(pkg, act=None):
    adb("shell", "am", "force-stop", pkg, t=90)
    time.sleep(2)
    if act:
        return adb("shell", "am", "start", "-n", f"{pkg}/{act}", t=180)
    return adb("shell", "monkey", "-p", pkg, "-c",
               "android.intent.category.LAUNCHER", "1", t=180)

def _dump_ui():
    adb("shell", "uiautomator", "dump", "/sdcard/a.xml", t=120)
    return adb("shell", "cat", "/sdcard/a.xml", t=90)

def dismiss_anr(rounds=6):
    for _ in range(rounds):
        x = _dump_ui()
        if "isn't responding" not in x and "无响应" not in x:
            return True
        mm = re.search(r'text="Wait"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', x)
        if not mm:
            return False
        x1, y1, x2, y2 = map(int, mm.groups())
        adb("shell", "input", "tap", (x1+x2)//2, (y1+y2)//2, t=60)
        L(f"  点 Wait @{(x1+x2)//2},{(y1+y2)//2}")
        time.sleep(12)
    return False

def tap_text(want, tries=6, wait=10):
    for _ in range(tries):
        x = _dump_ui()
        for mm in re.finditer(r"<node[^>]*>", x):
            tag = mm.group(0)
            if want in tag:
                b = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
                if b:
                    x1, y1, x2, y2 = map(int, b.groups())
                    adb("shell", "input", "tap", (x1+x2)//2, (y1+y2)//2, t=60)
                    L(f"  点「{want}」@{(x1+x2)//2},{(y1+y2)//2}")
                    return True
        time.sleep(wait)
    return False

QR_BOX = (150, 480, 930, 1250)      # 扫码页二维码所在区域（1080x1920）

def wait_activity(needle, timeout=25):
    t0 = time.time()
    while time.time() - t0 < timeout:
        a = adb("shell", "dumpsys activity activities | grep mResumedActivity | head -1", t=30)
        if needle in (a or ""):
            return True
        time.sleep(1)
    return False

def nav_qr():
    """推到 QQ 扫码页，返回是否成功"""
    L("  → QQ 登录")
    adb("shell", "input tap 1004 654", t=40)
    if not wait_activity("mobileqq", 30):
        L("  ✗ QQ 没起来")
        return False
    time.sleep(2)
    act = adb("shell", "dumpsys activity activities | grep mResumedActivity | head -1", t=30) or ""
    if "LoginActivity" in act:                  # 停在 QQ 首页（新用户/登录）
        adb("shell", "input tap 792 1546", t=40)
        time.sleep(3)
        act = adb("shell", "dumpsys activity activities | grep mResumedActivity | head -1", t=30) or ""
    if "LoginActivity" in act:                  # 登录表单页，点扫码
        L("  → 扫码登录")
        adb("shell", "input tap 418 1678", t=40)
        wait_activity("QQBrowserActivity", 25)
        time.sleep(2)
    return True

_SEQ = [0]

def shot(tag="s", small=False):
    """截图。用唯一文件名上传，避免 GitHub 同名文件读到旧内容的缓存问题。"""
    _SEQ[0] += 1
    stamp = f"{int(time.time())}_{_SEQ[0]}"
    try:
        if small:
            sh(f"{ADB} shell wm size 640x360", 60)
            time.sleep(2)
        d = sh(f"{ADB} exec-out screencap -p", 180, binary=True)
        if small:
            sh(f"{ADB} shell wm size reset", 60)
    except Exception:
        if small:
            sh(f"{ADB} shell wm size reset", 60)
        raise
    if not d or d[:4] != b"\x89PNG" or len(d) < 3000:
        return f"FAIL shot {len(d) if d else 0}B"
    open(WORK + f"/{tag}.png", "wb").write(d)

    raw = base64.b64encode(d).decode()
    n = (len(raw) + _chunk - 1) // _chunk
    files = [f"relay/s_{stamp}_{i}.b64" for i in range(n)]
    if n == 1:
        put(files[0], raw)
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as ex:
            list(ex.map(lambda i: put(files[i], raw[i*_chunk:(i+1)*_chunk]), range(n)))
    put("relay/mw_shot_meta.json", json.dumps(
        {"chunks": n, "bytes": len(d), "files": files, "ts": int(time.time()*1000)}))
    return f"OK shot {len(d)}B {n}chunks {stamp}"

# ───────────────────── 磁盘
def _writable(path):
    """建目录 + 改属主 + 实测可写。任何一步不行都返回 False。"""
    sh(f"sudo mkdir -p {path} 2>/dev/null || mkdir -p {path} 2>/dev/null || true", 90)
    sh(f"sudo chown -R $(id -u):$(id -g) {path} 2>/dev/null || true", 90)
    sh(f"chmod -R u+rwX {path} 2>/dev/null || true", 60)
    try:
        t = os.path.join(path, ".wtest")
        with open(t, "w") as f:
            f.write("x")
        os.remove(t)
        return True
    except Exception as e:
        L(f"  {path} 不可写: {e}")
        return False

def prepare_disk():
    global AVD_ROOT, WORK
    L("磁盘准备")
    for d in ["/usr/share/dotnet", "/opt/hostedtoolcache/CodeQL",
              "/usr/local/share/powershell", "/usr/local/lib/android/sdk/ndk",
              "/usr/local/lib/android/sdk/cmake", "/usr/share/swift",
              "/opt/az", "/usr/local/.ghcup"]:
        sh(f"sudo rm -rf {d} 2>/dev/null || true", 240)
    sh("sudo rm -rf /var/lib/apt/lists/* 2>/dev/null || true", 120)

    # /mnt 常属 root，mkdir 必须 sudo；不行就退回 HOME（同盘，32G 够用）
    if not (_writable(AVD_ROOT) and _writable(WORK)):
        L("回退到 $HOME")
        AVD_ROOT = HOME + "/.android/avd"
        WORK = HOME + "/mw"
        if not (_writable(AVD_ROOT) and _writable(WORK)):
            L("FAIL 找不到可写目录")
            raise SystemExit(5)

    L(f"AVD_ROOT = {AVD_ROOT}")
    L(f"WORK     = {WORK}")
    L("df:\n" + sh("df -h / | tail -1"))
    L("df AVD 所在盘:\n" + sh(f"df -h {AVD_ROOT} | tail -1"))

# ───────────────────── APK
def ensure_apk():
    if os.path.exists(APK) and os.path.getsize(APK) >= APK_MIN:
        L(f"APK 已存在 {os.path.getsize(APK)}B")
        return True
    for attempt in range(1, 4):
        L(f"下载 APK 第 {attempt} 次")
        sh(f"rm -f {APK}", 30)
        sh(f"curl -sL --retry 3 --retry-delay 5 -m 2700 -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)' "
           f"-o {APK} '{APK_URL}'", 2700)
        sz = os.path.getsize(APK) if os.path.exists(APK) else 0
        L(f"  得到 {sz} B")
        if sz < APK_MIN:
            continue
        md5 = sh(f"md5sum {APK} | cut -d' ' -f1", 300).strip()
        L(f"  MD5 {md5}")
        if not APK_MD5 or md5 == APK_MD5:
            L("  ✅ 通过")
            return True
    return False

# ───────────────────── 启动
L("=== mwctl 启动 ===")
prepare_disk()

sysdir = None
for root, dirs, files in os.walk(SDK + "/system-images"):
    if "android-30" in root and "kernel-ranchu" in files:
        sysdir = root + "/"
        break
if not sysdir:
    L("FAIL 没有 android-30 镜像")
    put(RES, "FAIL|no_image")
    raise SystemExit(2)
L("image = " + sysdir)

avdd = f"{AVD_ROOT}/{AVD}.avd"
os.makedirs(avdd, exist_ok=True)
os.makedirs(AVD_ROOT, exist_ok=True)
open(f"{AVD_ROOT}/{AVD}.ini", "w").write(
    f"avd.ini.encoding=UTF-8\npath={avdd}\npath.rel=avd/{AVD}.avd\ntarget=android-30\n")
open(f"{avdd}/config.ini", "w").write(f"""AvdId={AVD}
PlayStore.enabled=false
abi.type=x86_64
avd.ini.displayname={AVD}
avd.ini.encoding=UTF-8
disk.dataPartition.size=8G
hw.audioInput=no
hw.audioOutput=no
hw.cpu.arch=x86_64
hw.cpu.ncore=4
hw.gpu.enabled=yes
hw.gpu.mode=swiftshader_indirect
hw.keyboard=yes
hw.lcd.density=420
hw.lcd.height=1080
hw.lcd.width=1920
hw.mainKeys=no
hw.ramSize=8192
image.sysdir.1={sysdir}
runtime.network.latency=none
runtime.network.speed=full
showDeviceFrame=no
tag.id=google_apis
""")

sh("sudo chmod 666 /dev/kvm 2>/dev/null || true", 60)
L("KVM: " + ("有 ✅" if os.path.exists("/dev/kvm") else "无 ❌"))
sh(f"rm -f {avdd}/*.lock 2>/dev/null || true", 30)

env = (f"ANDROID_AVD_HOME={AVD_ROOT} ANDROID_SDK_ROOT={SDK} ANDROID_HOME={SDK} TMPDIR={WORK}")
L("启动模拟器")
sh(f"{env} nohup {EMU} -avd {AVD} -no-window -no-audio -no-boot-anim "
   f"-gpu swiftshader_indirect -no-snapshot -wipe-data -accel auto "
   f"-memory 8192 -cores 6 -partition-size 16384 "
   f"</dev/null > {WORK}/emu.log 2>&1 &", 60)

boot = False
for i in range(70):
    time.sleep(8)
    if adb("shell", "getprop", "sys.boot_completed", t=30) == "1":
        boot = True
        L(f"✅ 开机完成 {(i+1)*8}s")
        break
    if i % 6 == 5:
        L(f"开机中 {(i+1)*8}s | {sh(f'tail -3 {WORK}/emu.log', 15).strip()[-220:]}")
if not boot:
    L("FAIL 开机超时\n" + sh(f"tail -25 {WORK}/emu.log", 20)[-1500:])
    put(RES, "FAIL|boot")
    raise SystemExit(3)

sh("python3 -m pip install -q pillow 2>&1 | tail -1", 240)
try:
    import PIL; L("PIL = " + PIL.__version__)
except Exception as e:
    L("PIL 不可用: " + str(e))

# 清掉占内存的后台服务，给游戏腾空间
for _p in ("com.google.android.gms", "com.google.android.apps.photos",
           "com.google.android.apps.messaging", "com.android.chrome",
           "com.google.android.youtube", "com.google.android.apps.maps"):
    adb("shell", "am", "force-stop", _p, t=60)
L("已清理后台  free=" + (adb("shell", "free -m | head -2 | tail -1", t=60) or ""))

L("abilist = " + adb("shell", "getprop", "ro.product.cpu.abilist", t=30))
L("bridge  = " + (adb("shell", "getprop", "ro.dalvik.vm.native.bridge", t=30) or "(空)"))

# 等 package 服务稳定
for i in range(30):
    if adb("shell", "pm", "list", "packages", t=60).count("package:") > 100:
        L("package 服务就绪")
        break
    time.sleep(10)

# 装游戏
if PKG not in adb("shell", "pm", "list", "packages", t=90):
    if not ensure_apk():
        L("FAIL APK 拿不到有效文件")
        put(RES, "FAIL|apk")
        raise SystemExit(4)
    L(f"安装 {os.path.getsize(APK)/1048576:.0f} MB，预计 2-4 分钟")
    out = sh(f"{ADB} install -r -t -g {APK}", 2400)
    L("install → " + out.strip()[-400:])

L("游戏已装: " + str(pkg_installed(PKG)))

# （九游版不需要 QQ，跳过）

# ── 启动游戏 → 勾协议 → 拉 QQ → 扫码页
L("启动九游版")
force_start(PKG, None)
time.sleep(20)
dismiss_anr()
time.sleep(15)
dismiss_anr()
L("SHOT " + shot("boot1"))
put(RES, "READY|boot|ok")

# ───────────────────── 主循环
L("=== 等待命令 ===")
last = ""
while time.time() < DEADLINE:
    try:
        cur = (get(CMD) or "").strip()
        if cur and cur != last:
            last = cur
            body_line = cur.split("\n")[0]
            parts = body_line.split()
            op = parts[0].lower()
            L("> " + body_line[:200])
            r = ""

            if op == "shot":
                r = shot()
            elif op == "ui":
                adb("shell", "uiautomator", "dump", "/sdcard/u.xml", t=90)
                xml = adb("shell", "cat", "/sdcard/u.xml", t=60)
                items = []
                for m in re.finditer(r"<node[^>]*>", xml):
                    tag = m.group(0)
                    def g(k):
                        mm = re.search(k + r'="([^"]*)"', tag)
                        return mm.group(1) if mm else ""
                    t = g("text") or g("content-desc")
                    if not t or len(t) > 40:
                        continue
                    bm = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", g("bounds"))
                    if not bm:
                        continue
                    x1, y1, x2, y2 = map(int, bm.groups())
                    items.append({"t": t, "x": (x1+x2)//2, "y": (y1+y2)//2, "btn": g("clickable") == "true"})
                r = "OK|ui|" + json.dumps(items, ensure_ascii=False)
            elif op == "tap" and len(parts) >= 3:
                r = "OK|tap|" + adb("shell", "input", "tap", parts[1], parts[2], t=40)
            elif op == "swipe" and len(parts) >= 6:
                r = "OK|swipe|" + adb("shell", "input", "swipe", *parts[1:6], t=60)
            elif op == "text" and len(parts) >= 2:
                r = "OK|text|" + adb("shell", "input", "text",
                                    "'" + body_line.split(None, 1)[1].replace(" ", "%s") + "'", t=60)
            elif op == "key" and len(parts) >= 2:
                r = "OK|key|" + adb("shell", "input", "keyevent", parts[1], t=40)
            elif op == "start":
                r = "OK|start|" + adb("shell", "am", "start", "-n", f"{PKG}/{ACT}", t=180)
            elif op == "click" and len(parts) >= 2:
                want = body_line.split(None, 1)[1]
                adb("shell", "uiautomator", "dump", "/sdcard/u.xml", t=90)
                xml = adb("shell", "cat", "/sdcard/u.xml", t=60)
                hit = None
                for m in re.finditer(r"<node[^>]*>", xml):
                    tag = m.group(0)
                    if want in tag:
                        bm = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
                        if bm:
                            x1, y1, x2, y2 = map(int, bm.groups())
                            hit = ((x1+x2)//2, (y1+y2)//2)
                            break
                if hit:
                    adb("shell", "input", "tap", hit[0], hit[1], t=40)
                    r = f"OK|click|{want}@{hit[0]},{hit[1]}"
                else:
                    r = f"MISS|click|{want}"
            elif op == "shell":
                # 必须走 adb shell，直接在宿主机跑是错的
                r = "OK|shell|" + sh(f"{ADB} shell " + body_line.split(None, 1)[1], 240)[-900:]
            elif op == "inst" and len(parts) >= 2:
                f2 = WORK + "/extra.apk"
                sh(f"curl -sL -m 1200 -A 'Mozilla/5.0' -o {f2} '{parts[1]}'", 1200)
                r = "OK|inst|" + sh(f"{ADB} install -r -t {f2}", 1800)[-300:]
            elif op == "stop" and len(parts) >= 2:
                r = "OK|stop|" + adb("shell", "am", "force-stop", parts[1], t=90)
            elif op == "launch" and len(parts) >= 2:
                r = "OK|launch|" + force_start(parts[1], parts[2] if len(parts) > 2 else None)[-300:]
            elif op == "logcat":
                n = parts[1] if len(parts) > 1 else "200"
                r = "OK|logcat|" + adb("shell", "logcat", "-d", "-t", n, t=180)[-2000:]
            elif op == "qr":
                r = "OK|qr|" + shot("qr")
            elif op == "qrrefresh":
                L("qrrefresh")
                adb("shell", "input keyevent 4", t=40)
                time.sleep(2)
                adb("shell", "input tap 418 1678", t=40)
                wait_activity("QQBrowserActivity", 25)
                time.sleep(2)
                r = "OK|qr|" + shot("qr")
            elif op == "goqr":
                L("goqr")
                nav_qr()
                r = "OK|qr|" + shot("qr")
            elif op == "ping":
                r = "OK|pong"
            else:
                r = "ERR|unknown|" + op

            put(RES, r)
            if op in ("tap", "click", "key", "swipe", "start", "text"):
                time.sleep(2)
                shot("after")
        time.sleep(0.6)
    except Exception:
        L("LOOP " + traceback.format_exc()[-500:])
        time.sleep(2)

L("CONTROLLER_EXIT")
