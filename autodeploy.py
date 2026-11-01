import os
import sys
import subprocess
import shutil
import string
import json
import re
import secrets
import ctypes
import winreg
import urllib.request
import ssl
import zipfile
import threading
import time

ssl._create_default_https_context = ssl._create_unverified_context

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BBRepo = "https://github.com/waarl0rd/bubbabloxreborn.git"
RepoName = "bubbabloxreborn"          # folder git creates / we use (was bubbablox-v2)
PostgresPath = r"C:\Program Files\PostgreSQL\13\bin"
RBXRegPath = r"SOFTWARE\ROBLOX Corporation\Roblox"

# Every RCC folder that exists in the reborn repo
RCCFolders = ["RCCService", "RCCService2015", "RCCService2017", "RCCService2018", "RCCService2020"]

# ---------------------------------------------------------------------------
# Logging (print also goes to bbdeployer.log)
# ---------------------------------------------------------------------------
OrigPrint = print
def print(*args, **kwargs):
    OrigPrint(*args, **kwargs)
    try:
        Log = os.path.join(GetAppData(), "bbdeployer.log")
        with open(Log, "a", encoding="utf-8") as f:
            f.write(" ".join(str(a) for a in args) + "\n")
    except Exception:
        pass

def Clear():
    os.system('cls' if os.name == 'nt' else 'clear')

INSTALLERS = {
    "node": {
        "url": "https://nodejs.org/dist/v18.16.1/node-v18.16.1-x64.msi",
        "file": "node-v18.16.1-x64.msi",
        "cmd": 'msiexec /i "{file}" /quiet /qn /norestart'
    },
    "postgres": {
        "url": "https://sbp.enterprisedb.com/getfile.jsp?fileid=1258627",
        "file": "postgresql-13-windows-x64.exe",
        "cmd": '"{file}" --mode unattended --unattendedmodeui none --superpassword "{password}"'
    },
    "dotnet": {
        "url": "https://builds.dotnet.microsoft.com/dotnet/Sdk/6.0.412/dotnet-sdk-6.0.412-win-x64.exe",
        "file": "dotnet-sdk-6.0.412-win-x64.exe",
        "cmd": '"{file}" /quiet /norestart'
    },
    "go": {
        "url": "https://go.dev/dl/go1.20.6.windows-amd64.msi",
        "file": "go1.20.6.windows-amd64.msi",
        "cmd": 'msiexec /i "{file}" /quiet /qn /norestart'
    },
    "python": {
        "url": "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe",
        "file": "python-3.12.8-amd64.exe",
        "cmd": '"{file}" /quiet InstallAllUsers=1 PrependPath=1'
    },
    "git": {
        "url": "https://github.com/git-for-windows/git/releases/download/v2.53.0.windows.2/Git-2.53.0.2-64-bit.exe",
        "file": "Git-2.53.0.2-64-bit.exe",
        "cmd": '"{file}" /VERYSILENT /NORESTART'
    }
}

def RunCmd(command, cwd=None, shell=True, check=True, silent=False):
    if not silent:
        print(f"Running: {command}")
    try:
        result = subprocess.run(command, cwd=cwd, shell=shell, check=check, capture_output=True,
                                text=True, encoding='utf-8', errors='replace')
        if not check and result.returncode != 0:
            return None
        return result.stdout.strip() if result.stdout else ""
    except subprocess.CalledProcessError as e:
        if not silent:
            print(f"Error running command: {e}")
            print(f"Output: {e.stdout}")
            print(f"Error: {e.stderr}")
        if check:
            raise
        return None
    except FileNotFoundError:
        if not silent:
            print(f"Executable not found for command: {command}")
        if check:
            raise
        return None

class Spinner:
    def __init__(self, message="Working"):
        self.message = message
        self.running = False
        self.thread = None

    def spin(self):
        dots = 1
        while self.running:
            sys.stdout.write(f"\r{self.message}{'.' * dots}{' ' * (3 - dots)}")
            sys.stdout.flush()
            dots = dots + 1 if dots < 3 else 1
            time.sleep(0.4)
        sys.stdout.write(f"\r{' ' * (len(self.message) + 10)}\r")
        sys.stdout.flush()

    def start(self):
        self.running = True
        # daemon so a crash can never leave the script hanging on the spinner
        self.thread = threading.Thread(target=self.spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()
        return False

def CheckDeps():
    deps = {
        "git": "git --version",
        "node": "node -v",
        "npm": "npm -v",
        "dotnet": "dotnet --version",
        "go": "go version",
        "python": "python --version",
        "postgres": "psql --version",   # usually not on PATH, folder check below covers it
        "ffmpeg": "ffmpeg -version"
    }

    missing = []
    for name, cmd in deps.items():
        if RunCmd(cmd, check=False, silent=True) is None:
            if name == "postgres":
                if not os.path.exists(r"C:\Program Files\PostgreSQL"):
                    missing.append(name)
            elif name != "npm":
                missing.append(name)
    return missing

def Download(url, destination, name):
    with Spinner(f"Downloading {name}"):
        try:
            urllib.request.urlretrieve(url, destination)
            return True
        except Exception as e:
            print(f"\nFailed to download {name}: {e}")
            return False

def InstallPackages():
    packages = "fastapi aiohttp pydub uvicorn python-magic python-magic-bin==0.4.14 python-multipart cryptography"

    def run(cmd):
        try:
            subprocess.check_call(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except subprocess.CalledProcessError:
            return False

    if run(f"pip install {packages}"):
        return True
    if run(f"python -m pip install {packages}"):
        return True

    print("Pip failed, trying other locations")
    paths = []
    for v in ("311", "312", "313", "314"):
        paths.append(rf"C:\Program Files\Python{v}\python.exe")
        paths.append(rf"C:\Program Files (x86)\Python{v}\python.exe")
        paths.append(os.path.expandvars(rf"%LOCALAPPDATA%\Programs\Python\Python{v}\python.exe"))

    for py in paths:
        if os.path.exists(py):
            print(f"Trying: {py}")
            if run(f'"{py}" -m pip install {packages}'):
                return True

    print("Could not install any python packages, please manually install the packages!")
    print(f"They are: {packages}")
    input("Press enter to continue...")
    return False

def Install(name, RealDBPass=None):
    Clear()
    info = INSTALLERS[name]
    FilePath = os.path.join(GetAppData(), info["file"])

    if not os.path.exists(FilePath):
        if not Download(info["url"], FilePath, name):
            return False

    msg = f"Installing {name}"
    if name == "postgres":
        msg += " (This may take a while, approx 3-8 minutes)"
    cmd = info["cmd"].format(file=FilePath, password=RealDBPass)
    try:
        with Spinner(msg):
            RunCmd(cmd, silent=True)
        if name == "postgres":
            with open(os.path.join(GetAppData(), "pg_autoinstalled.txt"), "w") as f:
                f.write("1")
        return True
    except Exception as e:
        print(f"Installation failed or requires manual intervention for {name}: {e}")
        return False

def InstallFFMPEG():
    Clear()
    name = "ffmpeg"
    FFMpegUrl = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
    Destination = os.path.join(GetAppData(), "ffmpeg-release-essentials.zip")
    if not os.path.exists(Destination):
        if not Download(FFMpegUrl, Destination, name):
            return False

    FFMpegFolder = r"C:\ffmpeg"
    os.makedirs(FFMpegFolder, exist_ok=True)
    try:
        with Spinner(f"Installing {name}"):
            with zipfile.ZipFile(Destination, 'r') as ZipFileRef:
                ZipFileRef.extractall(FFMpegFolder)

            Bin = None
            for root, dirs, files in os.walk(FFMpegFolder):
                if "ffmpeg.exe" in files:
                    Bin = root
                    break

            if not Bin:
                print("Could not find ffmpeg.exe after extracting")
                return False

            PathCMD = (
                "[Environment]::SetEnvironmentVariable('Path', "
                "[Environment]::GetEnvironmentVariable('Path', [EnvironmentVariableTarget]::Machine) + "
                f"';{Bin}', [EnvironmentVariableTarget]::Machine)"
            )
            RunCmd(f'powershell -Command "{PathCMD}"', silent=True)
        return True
    except Exception as e:
        print(f"Failed to extract/install FFMPEG: {e}")
        return False

# ---------------------------------------------------------------------------
# Binary patching
# ---------------------------------------------------------------------------
def PatchFile(FilePath, SearchBytes, ReplaceBytes):
    """Exact same-length byte replace. Refuses to write if the size would change."""
    if not os.path.exists(FilePath):
        return False
    if len(SearchBytes) != len(ReplaceBytes):
        print(f"[{os.path.basename(os.path.dirname(FilePath))}] replacement length differs from target "
              f"({len(ReplaceBytes)} vs {len(SearchBytes)}), NOT patching (it would corrupt the exe)")
        return False

    with open(FilePath, 'rb') as f:
        Content = f.read()

    if SearchBytes not in Content:
        return False

    with open(FilePath, 'wb') as f:
        f.write(Content.replace(SearchBytes, ReplaceBytes))
    return True

def PatchRegex(FilePath, Pattern, NewBytes, Count=0):
    """Replace regex matches with NewBytes. Matches whose length differs are skipped (never corrupts)."""
    if not os.path.exists(FilePath):
        return 0
    with open(FilePath, 'rb') as f:
        Content = bytearray(f.read())

    matches = list(re.finditer(Pattern, bytes(Content), re.DOTALL))
    if Count:
        matches = matches[:Count]

    done = 0
    for m in reversed(matches):
        if len(m.group(0)) != len(NewBytes):
            print(f"Skipping a key in {os.path.relpath(FilePath)}: length {len(m.group(0))} != new key length {len(NewBytes)}")
            continue
        Content[m.start():m.end()] = NewBytes
        done += 1

    if done:
        with open(FilePath, 'wb') as f:
            f.write(Content)
    return done

def GetAppData():
    d = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'BBDeployer')
    os.makedirs(d, exist_ok=True)
    return d

def IsUserAdmin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def GetRandomStr(length=48):
    chars = string.ascii_letters + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def CleanAppData():
    folder = GetAppData()
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name == "bbdeployer.log":
            continue
        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except Exception as e:
            print(f"Couldn't delete {path} cause {e}")

def NpmBuild(BuildDir):
    """npm i + npm run build, but a failure only warns instead of killing the whole deploy."""
    print(f"Building {BuildDir}...")
    try:
        with Spinner(f"npm install in {os.path.basename(BuildDir)}"):
            RunCmd("npm i", cwd=BuildDir, silent=True)
        with Spinner(f"npm run build in {os.path.basename(BuildDir)}"):
            RunCmd("npm run build", cwd=BuildDir, silent=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Build failed in {BuildDir}:\n{(e.stderr or e.stdout or '')[-1500:]}")
        return False
    except Exception as e:
        print(f"Build failed in {BuildDir}: {e}")
        return False


def CloneRepo(RepoDir):
    """git clone with long paths on, no credential prompts, retries, and the REAL error shown."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    cmd = ['git', '-c', 'core.longpaths=true', '-c', 'http.postBuffer=524288000',
           '-c', 'http.version=HTTP/1.1', 'clone', '--progress', BBRepo, RepoDir]
    last = ""
    for attempt in range(1, 4):
        print(f"Cloning BubbaBlox (attempt {attempt}/3), this may take a while...")
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode == 0 and os.path.exists(os.path.join(RepoDir, "api")):
            return True
        last = (r.stderr or r.stdout or "").strip()
        print(f"git exit code {r.returncode}. git said:\n{last[-1500:]}\n")
        shutil.rmtree(RepoDir, ignore_errors=True)   # clear a half-finished clone
        time.sleep(3)

    print("Clone failed 3 times. Common fixes:")
    print(" - Run this from a SHORT path like C:\\BB (not Pictures/Desktop/OneDrive: Defender 'controlled folder access' and OneDrive sync can block writes).")
    print(" - Temporarily exclude the folder from antivirus; the repo contains .exe files that get quarantined mid-checkout.")
    print(" - 'schannel' / SSL errors: run  git config --global http.sslBackend openssl  and retry.")
    print(" - 'Repository not found': the repo may have been removed/renamed; check the URL in a browser.")
    return False

# ---------------------------------------------------------------------------
def main():
    if not IsUserAdmin():
        print("Please restart your shell/terminal as Administrator, or just re-run this as an Administrator.")
        input("Press Enter to close...")
        sys.exit(1)

    print("BubbaBlox AutoDeployer (reborn)")
    Missing = CheckDeps()
    AppData = GetAppData()
    DBPass = os.path.join(AppData, "dbpass.txt")

    if os.path.exists(DBPass):
        with open(DBPass, "r") as f:
            RealDBPass = f.read().strip()
    else:
        RealDBPass = input("Enter the password to your database: ").strip()
        while not RealDBPass:
            RealDBPass = input("Your DB password can't be empty, please enter a new one: ").strip()
        with open(DBPass, "w") as f:
            f.write(RealDBPass)

    if Missing:
        print(f"Found dependencies to be installed: {', '.join(Missing)}, will install now...")
        for m in Missing:
            print(f"\nInstalling {m}...")
            if m == "ffmpeg":
                InstallFFMPEG()
            elif m in INSTALLERS:
                Install(m, RealDBPass)
            else:
                print(f"Bad dependency: {m}, skipping")

        print("\nDependencies installed! Please restart your terminal/shell to update your PATH, then run the deployer again.")
        input("Press Enter to continue...")
        sys.exit(0)
    else:
        print("Dependencies installed, continuing...")

    # ---- gather settings ---------------------------------------------------
    while True:
        Clear()
        domain = input("Enter your site domain (has to be exactly 10 characters): ").strip()
        while len(domain) != 10:
            domain = input("Your domain has to be exactly 10 characters, please reenter: ").strip()

        if os.path.exists(os.path.join(GetAppData(), "pg_autoinstalled.txt")):
            db_name = "postgres"
            db_user = "postgres"
            pg_path = PostgresPath
        else:
            db_name = input("Enter your PostgreSQL database name: ").strip() or "postgres"
            db_user = input("Enter your PostgreSQL username: ").strip() or "postgres"
            pg_path = input(fr"Enter your bin path where PostgreSQL was installed (example: {PostgresPath}): ").strip() or PostgresPath

        Clear()
        print("To get your client ID and secret, you will have to make a new app here:")
        print("https://discord.com/developers/applications")
        print("Your client ID and secret will be under the OAuth2 section")
        input("Press enter to continue...")

        Clear()
        ClientID = input("Enter your Discord Client ID: ").strip()
        ClientSecret = input("Enter your Discord Client Secret: ").strip()
        Clear()
        WebhookURL = input("Enter your webhook URL: ").strip()

        Clear()
        HosterIP = input("Enter the IP of your gameserver host (example: 74.125.224.72): ").strip()
        while not HosterIP:
            HosterIP = input("The IP cannot be empty, please reenter: ").strip()

        GSPortRange = input("Enter your gameserver port range (example: 200-215): ").strip()
        while not re.match(r'^\d+-\d+$', GSPortRange):
            GSPortRange = input("Bad format! Use a format like 5-10, please reenter: ").strip()

        StartingPorty, EndingPorty = map(int, GSPortRange.split('-'))
        if StartingPorty > EndingPorty:
            StartingPorty, EndingPorty = EndingPorty, StartingPorty

        Clear()
        AccessKey = input("Enter your RCC's AccessKey (press Enter to generate randomly): ").strip()
        if not AccessKey:
            AccessKey = GetRandomStr()
            print(f"Generated Access Key: {AccessKey}")

        SettingsKey = input("Enter your RCC's SettingsKey (press Enter to generate randomly): ").strip()
        if not SettingsKey:
            SettingsKey = GetRandomStr()
            print(f"Generated SettingsKey: {SettingsKey}")

        JWTKey = GetRandomStr(64)
        BotAuth = GetRandomStr(48)
        Discorkey = GetRandomStr(48)
        IPSalt = GetRandomStr(64)
        SessionAuth = GetRandomStr(48)
        BubblemonsApiKey = GetRandomStr(32)

        Clear()
        print(f"Domain: {domain}")
        print(f"Discord Client ID: {ClientID}")
        print(f"Discord Client Secret: {ClientSecret}")
        print(f"Discord Webhook: {WebhookURL}")
        print(f"Public IP: {HosterIP}")
        print(f"Port Range: {StartingPorty}-{EndingPorty}")
        print(f"Access Key: {AccessKey}")
        print(f"Settings Key: {SettingsKey}")

        if input("Are these correct? (y/n) ").lower() == 'y':
            break
        Clear()
        print("Please re-enter your settings")

    # ---- clone -------------------------------------------------------------
    Clear()
    CurrentDir = os.getcwd()
    RepoDir = os.path.join(CurrentDir, RepoName)

    if not os.path.exists(RepoDir):
        if not CloneRepo(RepoDir):
            input("Press enter to close...")
            sys.exit(1)
    else:
        print("The repo's directory already exists, so we will skip cloning")

    # ---- python packages ---------------------------------------------------
    Clear()
    with Spinner("Installing Python packages"):
        InstallPackages()

    # ---- database ----------------------------------------------------------
    Clear()
    print("Setting up DB...")
    Schema = os.path.join(RepoDir, "api", "sql", "schema.sql")
    Psql = os.path.join(pg_path, "psql.exe")
    if not os.path.exists(Schema):
        print("Schema file not found! Please check your folder and make sure the script cloned the repo correctly.")
    elif not os.path.exists(Psql):
        print(f"psql.exe not found at {Psql}. Import api\\sql\\schema.sql manually.")
        input("Press enter to continue...")
    else:
        try:
            os.environ['PGPASSWORD'] = RealDBPass
            # -f with the full path: no copying into Program Files, no shell redirect, psql need not be on PATH
            RunCmd(f'"{Psql}" --username={db_user} --dbname={db_name} -f "{Schema}"', silent=True)
            print("Imported schema")
        except Exception as e:
            print(f"Failed to import schema: {e}")
            input("Press enter to continue...")

    # ---- appsettings -------------------------------------------------------
    Clear()
    print("Configuring website...")
    WebsiteDir = os.path.join(RepoDir, "Roblox", "Roblox.Website")
    AppSettingsExample = os.path.join(WebsiteDir, "appsettings.example.json")
    AppSettingsRealJson = os.path.join(WebsiteDir, "appsettings.json")

    Source = AppSettingsExample if os.path.exists(AppSettingsExample) else (
        AppSettingsRealJson if os.path.exists(AppSettingsRealJson) else None)

    if Source:
        with open(Source, 'r', encoding='utf-8-sig') as f:
            Content = f.read()

        PGPattern = r'"Postgres":\s*"[^"]*"'
        PgReplacement = f'"Postgres": "Host=127.0.0.1; Database={db_name}; Password={RealDBPass}; Username={db_user}; Maximum Pool Size=20"'
        Content = re.sub(PGPattern, lambda m: PgReplacement, Content)

        EscapedDir = RepoDir.replace("\\", "\\\\") + "\\\\"
        Content = Content.replace("C:\\\\Users\\\\Admin\\\\Desktop\\\\Revival\\\\ecsr\\\\ecsrev-main\\\\services\\\\", EscapedDir)
        Content = Content.replace("C:\\\\Users\\\\Admin\\\\Desktop\\\\Revival\\\\ecsr\\\\ecsrev-main\\\\services2021\\\\", EscapedDir)

        try:
            JsonData = json.loads(Content)
        except json.JSONDecodeError as e:
            print(f"Couldn't parse appsettings ({e}). Edit it by hand using the guide.")
            input("Press enter to continue...")
            JsonData = None

        if JsonData is not None:
            JsonData["BaseUrl"] = f"https://{domain}"
            JsonData["GSIPAddress"] = HosterIP
            JsonData.setdefault("GameServer", {})["AllowedNetworkPorts"] = list(range(StartingPorty, EndingPorty + 1))

            if WebhookURL:
                JsonData["Webhook"] = WebhookURL
                JsonData["SignupWebhook"] = WebhookURL

            JsonData["DiscordClientID"] = ClientID
            JsonData["DiscordClientSecret"] = ClientSecret
            JsonData["DiscordRedirect"] = f"https://{domain}/discordcb"
            JsonData["DiscordForgotPasswordRedirect"] = f"https://{domain}/forgotcb"
            JsonData["DiscordLoginRedirect"] = f"https://{domain}/logincb"
            JsonData["DiscordKey"] = Discorkey

            JsonData["IPSalt"] = IPSalt
            JsonData["Authorization"] = SessionAuth
            JsonData["BubbamonsApiKey"] = BubblemonsApiKey

            JsonData.setdefault("Jwt", {})["Sessions"] = JWTKey

            if "Render" in JsonData and isinstance(JsonData["Render"], dict):
                JsonData["Render"]["Authorization"] = AccessKey

            JsonData["GameServerAuthorization"] = AccessKey
            JsonData["RccAuthorization"] = AccessKey
            JsonData["BotAuthorization"] = BotAuth

            JsonData["AllowedQuietGetJson"] = [
                "ClientAppSettings",
                f"RCCService{SettingsKey}",
                "avatar-colors",
                f"RCC2015M{SettingsKey}",
                f"RCC2017E{SettingsKey}",
                "2015MAppSettings",
                "2017fflag",
                SettingsKey
            ]

            with open(AppSettingsRealJson, 'w', encoding='utf-8') as f:
                json.dump(JsonData, f, indent=4)
            if os.path.exists(AppSettingsExample):
                os.remove(AppSettingsExample)
            print("Configured appsettings.json")
    else:
        print("appsettings.example.json not found, skipping website config")

    GSExample = os.path.join(WebsiteDir, "game-servers.example.json")
    GSJson = os.path.join(WebsiteDir, "game-servers.json")
    if os.path.exists(GSExample):
        shutil.copy(GSExample, GSJson)
        os.remove(GSExample)
        print("Created GS Json")

    # ---- renderer config ---------------------------------------------------
    print("Configuring renderer...")
    RenderExample = os.path.join(RepoDir, "renderer", "config.example.json")
    RenderJson = os.path.join(RepoDir, "renderer", "config.json")
    if os.path.exists(RenderExample):
        with open(RenderExample, 'r', encoding='utf-8-sig') as f:
            Render_JsonData = json.load(f)

        for k in ("authorization", "Authorization"):
            if k in Render_JsonData:
                Render_JsonData[k] = AccessKey
        if "websiteBotAuth" in Render_JsonData:
            Render_JsonData["websiteBotAuth"] = BotAuth
        if WebhookURL:
            Render_JsonData["webhook"] = WebhookURL
        if "baseUrl" in Render_JsonData:
            Render_JsonData["baseUrl"] = f"https://{domain}"
        if "rcc" in Render_JsonData:
            Render_JsonData["rcc"] = os.path.join(RepoDir, "RCCService")

        with open(RenderJson, 'w', encoding='utf-8') as f:
            json.dump(Render_JsonData, f, indent=4)
        os.remove(RenderExample)
        print("Renderer config done")

    # ---- folders -----------------------------------------------------------
    Clear()
    print("Creating asset folders...")
    APIDirectory = os.path.join(RepoDir, "api")
    os.makedirs(os.path.join(APIDirectory, "storage", "asset"), exist_ok=True)
    os.makedirs(os.path.join(APIDirectory, "public", "images", "thumbnails"), exist_ok=True)
    os.makedirs(os.path.join(APIDirectory, "public", "images", "groups"), exist_ok=True)

    # ---- CORS --------------------------------------------------------------
    CorsMiddleware = os.path.join(WebsiteDir, "Middleware", "CorsMiddleware.cs")
    if os.path.exists(CorsMiddleware):
        with open(CorsMiddleware, 'r', encoding='utf-8-sig') as f:
            cors_Content = f.read()
        cors_Content = cors_Content.replace("bbblox.org", domain)
        with open(CorsMiddleware, 'w', encoding='utf-8') as f:
            f.write(cors_Content)
        print("Patched CORS with domain")

    # ---- frontend ----------------------------------------------------------
    Clear()
    print("Building frontend, may take a while...")
    Frontend_2016Example = os.path.join(RepoDir, "2016-roblox-main", "config.example.json")
    Frontend_2016Config = os.path.join(RepoDir, "2016-roblox-main", "config.json")
    if os.path.exists(Frontend_2016Example):
        with open(Frontend_2016Example, 'r', encoding='utf-8-sig') as f:
            Frontend_2016Content = f.read()
        Frontend_2016Content = Frontend_2016Content.replace("your.domain", domain)
        with open(Frontend_2016Config, 'w', encoding='utf-8') as f:
            f.write(Frontend_2016Content)
        os.remove(Frontend_2016Example)

    # admin is part of the guide, so build it too (was commented out before)
    for BuildDir in [os.path.join(RepoDir, "admin"),
                     os.path.join(RepoDir, "2016-roblox-main"),
                     os.path.join(RepoDir, "renderer")]:
        if os.path.exists(BuildDir):
            NpmBuild(BuildDir)

    # ---- registry ----------------------------------------------------------
    Clear()
    print("Setting up registry...")
    try:
        key = winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, RBXRegPath, 0,
                                 winreg.KEY_SET_VALUE | winreg.KEY_WOW64_32KEY)
        winreg.SetValueEx(key, "AccessKey", 0, winreg.REG_SZ, AccessKey)
        winreg.SetValueEx(key, "SettingsKey", 0, winreg.REG_SZ, SettingsKey)
        winreg.CloseKey(key)
        print("Setup reg keys")
    except Exception as e:
        print(f"Failed to set registry keys: {e}")
        input("Press enter to continue...")

    SettingsJsonDir = os.path.join(RepoDir, "Roblox", "Roblox.Libraries", "Json")
    if os.path.exists(SettingsJsonDir):
        target = f"RCCService{SettingsKey}.json"
        if not os.path.exists(os.path.join(SettingsJsonDir, target)):
            for File in os.listdir(SettingsJsonDir):
                if "RCCService" in File and File.endswith(".json"):
                    shutil.move(os.path.join(SettingsJsonDir, File), os.path.join(SettingsJsonDir, target))
                    break

    ClientData_cs = os.path.join(WebsiteDir, "Controllers", "Internal", "Other", "ClientData.cs")
    if os.path.exists(ClientData_cs):
        with open(ClientData_cs, 'r', encoding='utf-8-sig') as f:
            Clientdata_content = f.read()
        Clientdata_content = Clientdata_content.replace("RCCServiceBubbleRev2021RCCIsSoTuff", f"RCCService{SettingsKey}")
        with open(ClientData_cs, 'w', encoding='utf-8') as f:
            f.write(Clientdata_content)
        print("Updated ClientData")

    # ---- RSA ---------------------------------------------------------------
    Clear()
    print("Generating RSA keys...")
    RSADir = os.path.join(WebsiteDir, "RSA")
    if os.path.exists(RSADir):
        try:
            RunCmd("python Generate.py", cwd=RSADir)
            print("Generated RSA")
        except Exception as e:
            print(f"RSA generation failed: {e}")
            input("Press enter to continue...")

    # ---- patch RCCs --------------------------------------------------------
    Clear()
    print("Patching RCCs...")
    RCCDirs = [os.path.join(RepoDir, f) for f in RCCFolders]

    for d in RCCDirs:
        exe = os.path.join(d, "RCCService.exe")
        if os.path.exists(exe):
            if PatchFile(exe, b"bbblox.org", domain.encode('ascii')):
                print(f"Patched domain in {os.path.basename(d)}")
            else:
                print(f"{os.path.basename(d)}: no 'bbblox.org' found (already patched?)")
        Xml = os.path.join(d, "AppSettings.xml")
        if os.path.exists(Xml):
            with open(Xml, 'r', encoding='utf-8', errors='ignore') as f:
                xml_Content = f.read()
            xml_Content = xml_Content.replace("bbblox.org", domain)
            with open(Xml, 'w', encoding='utf-8') as f:
                f.write(xml_Content)

    # 2015/2016/2017/2018 use the base64 RSA blob (starts with BgIAAACkAABSU0Ex...)
    Pub2016 = os.path.join(RSADir, "PublicKey2016.pub")
    BlobPattern = rb'BgIAAACkAABSU0ExAAQAAAEAAQ[A-Za-z0-9+/]+={0,2}'
    if os.path.exists(Pub2016):
        with open(Pub2016, 'r') as f:
            NewPub = f.read().strip().encode('ascii')

        # (folder, how many keys to replace; 0 = all). 2018 guide says only the first.
        for folder, count in (("RCCService", 0), ("RCCService2015", 1), ("RCCService2017", 1), ("RCCService2018", 1)):
            exe = os.path.join(RepoDir, folder, "RCCService.exe")
            if os.path.exists(exe):
                n = PatchRegex(exe, BlobPattern, NewPub, Count=count)
                print(f"{folder}: replaced {n} RSA key(s)")
    else:
        print("PublicKey2016.pub not found, skipped 2015-2018 key patch")

    # 2020 uses PEM, every copy must be replaced
    Pub2020 = os.path.join(RSADir, "PublicKey2020.pub")
    if os.path.exists(Pub2020):
        with open(Pub2020, 'rb') as f:
            New2020Bytes = f.read().strip() + b'\x0A'
        PemPattern = rb'-----BEGIN PUBLIC KEY-----\r?\n.*?-----END PUBLIC KEY-----\n'
        exe = os.path.join(RepoDir, "RCCService2020", "RCCService.exe")
        if os.path.exists(exe):
            n = PatchRegex(exe, PemPattern, New2020Bytes)
            print(f"RCCService2020: replaced {n} RSA key(s)")
    else:
        print("PublicKey2020.pub not found, skipped 2020 key patch")

    CleanAppData()
    Clear()
    print("Bubba deployed! Please do these things after install")
    print("1. Go back to the Discord Developer Portal, go into your app and in the OAuth2 section add these redirect URL's:")
    print(f"\nhttps://{domain}/discordcb, https://{domain}/forgotcb, https://{domain}/logincb\n")
    print(f"2. Run the site with the runall.bat file in the {RepoName} directory")
    print("3. Create your admin account, it can be any name (example: Roblox)")
    print("4. Go to /admin and create a player with the ID 2500, and the name as UGC.")
    print("Then create the account with the ID 12, and the name as BadDecisions. Nullify the password for UGC and BadDecisions.")
    print("Finally, download and install DirectX onto your host so 2018/2020 can work.")
    print("You can download and get patching instructions for clients at https://zawg.ca/assets/bubbaclients")
    print(f"You will also have to forward all the ports in your port range which was {StartingPorty}-{EndingPorty}")
    print("either through your firewall or your router. (or both)")
    input("Press Enter to close...")

if __name__ == "__main__":
    main()