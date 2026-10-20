using System.Buffers.Binary;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace RuVoiceInstaller;

internal sealed class PayloadManifest
{
    public Dictionary<string, string> Files { get; set; } = new();
}

internal sealed class InstallState
{
    public string Status { get; set; } = "installed";
    public string GameExeHash { get; set; } = "";
    public Dictionary<string, string> Original { get; set; } = new();
    public Dictionary<string, string> Patched { get; set; } = new();
    public Dictionary<string, string> OwnedDlls { get; set; } = new();
    public Dictionary<string, string> ModFiles { get; set; } = new();
    public Dictionary<string, string> ModifiedDats { get; set; } = new();
    public Dictionary<string, long> DatLengthsBefore { get; set; } = new();
}

internal static class DiagnosticLog
{
    private static readonly object Gate = new();
    internal const string FileName = "ru_voice_installer.log";

    internal static void Write(string game, string message)
    {
        if (!Directory.Exists(game)) return;
        lock (Gate)
        {
            string file = Path.Combine(game, FileName);
            if (File.Exists(file) && new FileInfo(file).Length > 2_000_000)
                File.Move(file, Path.Combine(game, "ru_voice_installer.previous.log"), true);
            File.AppendAllText(file, $"[{DateTimeOffset.Now:yyyy-MM-dd HH:mm:ss zzz}] {message.Replace('\r', ' ').Replace('\n', ' ')}{Environment.NewLine}");
        }
    }

    internal static T Run<T>(string game, string action, Func<T> operation)
    {
        Write(game, "START " + action);
        try
        {
            T result = operation();
            Write(game, "OK " + action);
            return result;
        }
        catch (Exception error)
        {
            Write(game, "FAIL " + action + ": " + error);
            throw;
        }
    }
}

internal static class Operations
{
    internal const int MinimumBuild = 1269579;
    private static readonly Regex GameVersionPattern = new(
        @"(?<!\d)(?<build>\d{6,10})\|\^/game\d+/branches/release_(?<major>\d+)\.(?<minor>\d+)\|[^\x00\r\n]{1,100}",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);
    private static readonly byte[][] HookSignatures =
    [
        Convert.FromHexString("48895C2410488974241848897C2420554154415541564157488D6C24C94881ECC00000008B712833C04D8BE84C8BFA48"),
        Convert.FromHexString("48895C2410488974241848897C2420554154415541564157488D6C24C94881ECC0000000448B711033C0498BD84C8BEA"),
        Convert.FromHexString("4489442418555741564881EC80000000418BD0498BF9488B")
    ];
    private static readonly string[] IndexFiles = ["enshrouded.kfc", "enshrouded.kfc_resources"];
    private static readonly string[] DllFiles = ["dbghelp.dll", "winmm.dll", "shroudtopia.dll"];
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, PropertyNameCaseInsensitive = true };

    internal static string Payload => Path.Combine(AppContext.BaseDirectory, "payload");
    private static string Backup(string game) => Path.Combine(game, ".ru_voice_backup");
    private static string StatePath(string game) => Path.Combine(Backup(game), "state.json");
    private static string ModPath(string game) => Path.Combine(game, "mods", "ru_voice_separate_525");
    private static string PreviousModPath(string game) => Path.Combine(game, "mods", "ru_voice_separate_520");

    private static string VersionFromIndex(string index)
    {
        if (!File.Exists(index)) throw new InvalidOperationException("Не найден индекс enshrouded.kfc.");
        // The version is stored as plain ASCII in the KFC index, including EML-patched indices.
        string data = Encoding.ASCII.GetString(File.ReadAllBytes(index));
        var versions = GameVersionPattern.Matches(data).Select(x => x.Value).Distinct().ToArray();
        if (versions.Length != 1)
            throw new InvalidOperationException("Не удалось однозначно определить версию игрового индекса.");
        var match = GameVersionPattern.Match(versions[0]);
        if (!int.TryParse(match.Groups["build"].Value, out int build) ||
            !int.TryParse(match.Groups["major"].Value, out int major) ||
            !int.TryParse(match.Groups["minor"].Value, out int minor) ||
            major < 1 || build < MinimumBuild)
            throw new InvalidOperationException($"Сборка игры {match.Groups["build"].Value} старше минимальной {MinimumBuild}.");
        return versions[0];
    }

    internal static string GameVersion(string game) => VersionFromIndex(Path.Combine(game, "enshrouded.kfc"));

    private static void CheckRuntimeSignatures(string exePath)
    {
        byte[] exe = File.ReadAllBytes(exePath);
        if (exe.Length < 0x100 || BinaryPrimitives.ReadUInt16LittleEndian(exe) != 0x5a4d)
            throw new InvalidOperationException("enshrouded.exe не является ожидаемым PE-файлом.");
        int pe = BinaryPrimitives.ReadInt32LittleEndian(exe.AsSpan(0x3c));
        if (pe < 0 || pe > exe.Length - 24 || BinaryPrimitives.ReadUInt32LittleEndian(exe.AsSpan(pe)) != 0x4550)
            throw new InvalidOperationException("Неверный заголовок enshrouded.exe.");
        int count = BinaryPrimitives.ReadUInt16LittleEndian(exe.AsSpan(pe + 6));
        int optionalSize = BinaryPrimitives.ReadUInt16LittleEndian(exe.AsSpan(pe + 20));
        int sections = pe + 24 + optionalSize;
        if (count <= 0 || count > 96 || sections < 0 || sections > exe.Length - count * 40)
            throw new InvalidOperationException("Неверная таблица секций enshrouded.exe.");
        ReadOnlySpan<byte> code = default;
        for (int i = 0; i < count; i++)
        {
            var section = exe.AsSpan(sections + i * 40, 40);
            if (!section[..5].SequenceEqual(".text"u8)) continue;
            uint length = BinaryPrimitives.ReadUInt32LittleEndian(section[16..]);
            uint offset = BinaryPrimitives.ReadUInt32LittleEndian(section[20..]);
            if (offset > exe.Length || length > exe.Length - offset)
                throw new InvalidOperationException("Секция кода enshrouded.exe повреждена.");
            code = exe.AsSpan((int)offset, (int)length);
            break;
        }
        if (code.IsEmpty) throw new InvalidOperationException("Секция кода enshrouded.exe не найдена.");
        for (int i = 0; i < HookSignatures.Length; i++)
        {
            int first = code.IndexOf(HookSignatures[i]);
            if (first < 0 || code[(first + 1)..].IndexOf(HookSignatures[i]) >= 0)
                throw new InvalidOperationException($"Аудиофункция {i + 1} в enshrouded.exe изменилась или неоднозначна. Установка остановлена.");
        }
    }

    internal static string Hash(string path)
    {
        using var file = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(file)).ToLowerInvariant();
    }

    private static void CheckClosed()
    {
        if (Process.GetProcessesByName("enshrouded").Length != 0)
            throw new InvalidOperationException("Закройте Enshrouded перед изменением файлов.");
        if (Process.GetProcessesByName("VoiceInstaller").Length > 1)
            throw new InvalidOperationException("Открыто несколько окон установщика. Закройте лишние окна.");
    }

    private static void CheckGame(string game)
    {
        if (!File.Exists(Path.Combine(game, "enshrouded.exe")))
            throw new InvalidOperationException("В указанной папке нет enshrouded.exe.");
        string version = GameVersion(game);
        if (!File.Exists(Path.Combine(game, "enshrouded.kfc_resources")))
            throw new InvalidOperationException("Не найден индекс enshrouded.kfc_resources.");
        CheckRuntimeSignatures(Path.Combine(game, "enshrouded.exe"));
        DiagnosticLog.Write(game, "Game version: " + version);
        DiagnosticLog.Write(game, "Three unique runtime hook signatures confirmed");
        DiagnosticLog.Write(game, "enshrouded.exe SHA-256: " + Hash(Path.Combine(game, "enshrouded.exe")));
        foreach (string name in IndexFiles)
            DiagnosticLog.Write(game, name + " SHA-256: " + Hash(Path.Combine(game, name)));
    }

    private static string SafePayloadPath(string name)
    {
        string root = Path.GetFullPath(Payload) + Path.DirectorySeparatorChar;
        string path = Path.GetFullPath(Path.Combine(Payload, name.Replace('/', Path.DirectorySeparatorChar)));
        if (!path.StartsWith(root, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("Неверный путь в пакете.");
        return path;
    }

    private static PayloadManifest VerifyPayload()
    {
        string manifestPath = Path.Combine(Payload, "manifest.json");
        var manifest = JsonSerializer.Deserialize<PayloadManifest>(File.ReadAllText(manifestPath), JsonOptions)
                       ?? throw new InvalidOperationException("Манифест пакета пуст.");
        if (manifest.Files.Count != 1718) throw new InvalidOperationException("Пакет озвучки неполный.");
        foreach (var item in manifest.Files)
            if (!File.Exists(SafePayloadPath(item.Key)) || Hash(SafePayloadPath(item.Key)) != item.Value)
                throw new InvalidOperationException("Пакет повреждён: " + item.Key);
        return manifest;
    }

    private static InstallState? ReadState(string game)
    {
        string path = StatePath(game);
        return File.Exists(path) ? JsonSerializer.Deserialize<InstallState>(File.ReadAllText(path), JsonOptions) : null;
    }

    private static void SaveState(string game, InstallState state)
    {
        string target = StatePath(game), temp = target + ".tmp";
        File.WriteAllText(temp, JsonSerializer.Serialize(state, JsonOptions));
        File.Move(temp, target, true);
    }

    private static Dictionary<string, long> DatLengths(string game) =>
        Directory.GetFiles(game, "enshrouded_*.dat").ToDictionary(
            path => Path.GetFileName(path)!, path => new FileInfo(path).Length, StringComparer.OrdinalIgnoreCase);

    private static void CheckModFiles(string game, InstallState state)
    {
        string root = ModPath(game);
        if (!Directory.Exists(root) || (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
            throw new InvalidOperationException("Папка русской озвучки отсутствует или является ссылкой.");
        var expected = state.ModFiles.ToDictionary(x => x.Key.Replace('/', Path.DirectorySeparatorChar), x => x.Value,
                          StringComparer.OrdinalIgnoreCase);
        var actual = Directory.GetFiles(root, "*", SearchOption.AllDirectories)
            .ToDictionary(x => Path.GetRelativePath(root, x), Hash, StringComparer.OrdinalIgnoreCase);
        if (Directory.GetFileSystemEntries(root, "*", SearchOption.AllDirectories)
            .Any(x => (File.GetAttributes(x) & FileAttributes.ReparsePoint) != 0))
            throw new InvalidOperationException("В папке мода обнаружена ссылка.");
        if (actual.Count != expected.Count || expected.Any(x => !actual.TryGetValue(x.Key, out var hash) || hash != x.Value))
            throw new InvalidOperationException("Папка мода изменена; автоматическое удаление остановлено.");
    }

    private static bool IsLoaderRefresh(string game, InstallState state)
    {
        try
        {
            string mods = Path.Combine(game, "mods");
            if (Directory.GetFileSystemEntries(mods).Any(x =>
                    !string.Equals(Path.GetFullPath(x), Path.GetFullPath(ModPath(game)), StringComparison.OrdinalIgnoreCase)))
                return false;
            string bak = Path.Combine(game, "enshrouded.kfc.bak");
            if (!File.Exists(bak) || Hash(bak) != state.Original["enshrouded.kfc"])
                return false;
            foreach (string name in IndexFiles)
            {
                long original = new FileInfo(Path.Combine(Backup(game), name)).Length;
                long current = new FileInfo(Path.Combine(game, name)).Length;
                if (current < original || current > original + 4_000_000) return false;
            }
            foreach (var item in state.ModifiedDats)
                if (!File.Exists(Path.Combine(game, item.Key)) || Hash(Path.Combine(game, item.Key)) != item.Value)
                    return false;
            return true;
        }
        catch { return false; }
    }

    internal static string Status(string game)
    {
        CheckGame(game);
        var state = ReadState(game);
        if (Directory.Exists(PreviousModPath(game)))
            return "Найдена версия на 520 записей. Сначала отключите её прежним установщиком.";
        if (state is null)
        {
            if (Directory.Exists(ModPath(game)))
                return "Найден прежний тестовый мод. Перед установкой пакета требуется его штатный откат.";
            return "Сборка не старше минимальной. При установке будут проверены 1118 звуковых ссылок.";
        }
        if (state.Status == "restored") return "Оригинал восстановлен. Резервная копия сохранена.";
        if (state.Status != "installed") return "Неизвестное состояние установщика.";
        bool refreshed = IndexFiles.Any(name =>
            !File.Exists(Path.Combine(game, name)) || Hash(Path.Combine(game, name)) != state.Patched[name]);
        if (refreshed)
        {
            try { CheckModFiles(game, state); }
            catch { return "Файлы мода изменились после установки. Требуется ручная проверка."; }
            if (!IsLoaderRefresh(game, state))
                return "Игровые файлы изменились после установки. Требуется ручная проверка.";
        }
        foreach (var item in state.OwnedDlls)
            if (!File.Exists(Path.Combine(game, item.Key)) || Hash(Path.Combine(game, item.Key)) != item.Value)
                return "Файл загрузки мода изменился после установки. Требуется проверка.";
        if (state.ModFiles.Count == 528)
            return "Установлена прежняя версия: 525 страниц. Для обновления нажмите «Отключить · копию сохранить», затем «Установить мод».";
        return refreshed
            ? "Русская озвучка установлена: 525 страниц и 593 реплики персонажей. Индекс обновлён загрузчиком при запуске игры."
            : "Русская озвучка установлена: 525 страниц и 593 реплики персонажей, F3 включает и выключает её.";
    }

    internal static void Install(string game)
    {
        CheckClosed();
        CheckGame(game);
        if (Directory.Exists(PreviousModPath(game)))
            throw new InvalidOperationException("Сначала отключите версию на 520 записей прежним установщиком.");
        var manifest = VerifyPayload();
        var oldState = ReadState(game);
        if (oldState?.Status == "installed") throw new InvalidOperationException("Мод уже установлен.");
        if (oldState is not null && oldState.Status != "restored")
            throw new InvalidOperationException("Неизвестное состояние резервной копии.");
        foreach (string name in IndexFiles)
            if (!File.Exists(Path.Combine(game, name)))
                throw new InvalidOperationException("Не найден игровой индекс: " + name);
        string loaderBackup = Path.Combine(game, "enshrouded.kfc.bak");
        if (File.Exists(loaderBackup) && Hash(loaderBackup) != Hash(Path.Combine(game, "enshrouded.kfc")))
        {
            string backupVersion = VersionFromIndex(loaderBackup);
            if (backupVersion == GameVersion(game))
                throw new InvalidOperationException("Найден индекс, уже изменённый другим модом. Установка остановлена; подробности в журнале.");
        }
        string mod = ModPath(game), backup = Backup(game);
        if (Directory.Exists(mod)) throw new InvalidOperationException("Папка ru_voice_separate_525 уже существует.");
        if (oldState is null && Directory.Exists(backup))
            throw new InvalidOperationException("Папка .ru_voice_backup уже существует.");
        var state = oldState ?? new InstallState();
        state.GameExeHash = Hash(Path.Combine(game, "enshrouded.exe"));
        state.DatLengthsBefore = DatLengths(game);
        state.OwnedDlls.Clear();
        state.ModifiedDats.Clear();
        state.ModFiles = manifest.Files.Where(x => x.Key.StartsWith("mod/", StringComparison.Ordinal))
            .ToDictionary(x => x.Key[4..], x => x.Value, StringComparer.OrdinalIgnoreCase);
        if (oldState is null) Directory.CreateDirectory(backup);
        foreach (string name in IndexFiles)
        {
            string source = Path.Combine(game, name), target = Path.Combine(backup, name);
            if (oldState is null) File.Copy(source, target, false);
            else if (oldState.Status == "restored" && Hash(target) != Hash(source))
                File.Copy(source, target, true);
            string originalHash = Hash(source);
            if (Hash(target) != originalHash) throw new InvalidOperationException("Резервная копия не прошла проверку.");
            state.Original[name] = originalHash;
        }
        if (oldState is not null) SaveState(game, state);
        try
        {
            foreach (var item in manifest.Files.Where(x => x.Key.StartsWith("mod/", StringComparison.Ordinal)))
            {
                string target = Path.Combine(mod, item.Key[4..].Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.Copy(SafePayloadPath(item.Key), target, false);
            }
            foreach (string name in DllFiles)
            {
                string source = SafePayloadPath("native/" + name), target = Path.Combine(game, name);
                if (File.Exists(target))
                {
                    if (Hash(target) != Hash(source))
                        throw new InvalidOperationException("Конфликт с уже установленным " + name);
                }
                else
                {
                    File.Copy(source, target);
                    state.OwnedDlls[name] = Hash(source);
                }
            }
            RunEmm(game);
            foreach (string name in IndexFiles) state.Patched[name] = Hash(Path.Combine(game, name));
            if (state.Patched.All(x => x.Value == state.Original[x.Key]))
                throw new InvalidOperationException("EML не изменил игровой индекс.");
            foreach (var item in DatLengths(game))
            {
                state.DatLengthsBefore.TryGetValue(item.Key, out long before);
                if (item.Value != before)
                {
                    if (before != 0) throw new InvalidOperationException("EML изменил непустой DAT: " + item.Key);
                    state.ModifiedDats[item.Key] = Hash(Path.Combine(game, item.Key));
                }
            }
            state.Status = "installed";
            SaveState(game, state);
        }
        catch (Exception error)
        {
            DiagnosticLog.Write(game, "Install failed; restoring original indices: " + error.Message);
            foreach (string name in IndexFiles)
                File.Copy(Path.Combine(backup, name), Path.Combine(game, name), true);
            foreach (var item in DatLengths(game))
            {
                state.DatLengthsBefore.TryGetValue(item.Key, out long before);
                if (before == 0 && item.Value != 0)
                {
                    if (state.DatLengthsBefore.ContainsKey(item.Key))
                        using (var file = File.OpenWrite(Path.Combine(game, item.Key))) file.SetLength(0);
                    else File.Delete(Path.Combine(game, item.Key));
                }
            }
            if (Directory.Exists(mod)) Directory.Delete(mod, true);
            foreach (var item in state.OwnedDlls)
            {
                string target = Path.Combine(game, item.Key);
                if (File.Exists(target) && Hash(target) == item.Value) File.Delete(target);
            }
            if (oldState is null && Directory.Exists(backup)) Directory.Delete(backup, true);
            if (oldState is not null)
            {
                state.Status = "restored";
                SaveState(game, state);
            }
            DiagnosticLog.Write(game, "Rollback complete");
            throw;
        }
    }

    private static void RunEmm(string game)
    {
        using var process = new Process();
        process.StartInfo = new ProcessStartInfo(SafePayloadPath("tools/emm.exe"))
        {
            Arguments = "run -p -g \"" + game + "\"",
            WorkingDirectory = game,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        process.Start();
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(900000))
        {
            process.Kill(true);
            throw new InvalidOperationException("EML не завершился за 15 минут.");
        }
        string output = stdout.GetAwaiter().GetResult() + stderr.GetAwaiter().GetResult();
        DiagnosticLog.Write(game, $"EML exit={process.ExitCode}, mapped={output.Split("RU_VOICE_MAP ").Length - 1}");
        if (process.ExitCode != 0 || output.Split("RU_VOICE_MAP ").Length - 1 != 1118)
        {
            DiagnosticLog.Write(game, "EML failure tail: " + output[^Math.Min(output.Length, 4000)..]);
            throw new InvalidOperationException("EML не создал 1118 записей. " + output[^Math.Min(output.Length, 700)..]);
        }
    }

    internal static void Restore(string game, bool deleteBackup)
    {
        CheckClosed();
        if (!File.Exists(Path.Combine(game, "enshrouded.exe")))
            throw new InvalidOperationException("В указанной папке нет enshrouded.exe.");
        var state = ReadState(game) ?? throw new InvalidOperationException("Установка не найдена.");
        string backup = Backup(game);
        if (state.Status == "installed")
        {
            CheckModFiles(game, state);
            if (GameVersion(game) != VersionFromIndex(Path.Combine(backup, "enshrouded.kfc")))
                throw new InvalidOperationException("Игра обновилась после установки мода. Старую копию индекса нельзя безопасно восстановить поверх новой сборки.");
            foreach (string name in IndexFiles)
                if (!File.Exists(Path.Combine(backup, name)) || Hash(Path.Combine(backup, name)) != state.Original[name])
                    throw new InvalidOperationException("Резервная копия повреждена: " + name);
            if (IndexFiles.Any(name => !File.Exists(Path.Combine(game, name)) ||
                                       Hash(Path.Combine(game, name)) != state.Patched[name]) &&
                !IsLoaderRefresh(game, state))
                throw new InvalidOperationException("Индекс изменён неизвестным способом; автоматическое восстановление остановлено.");
            foreach (var item in state.OwnedDlls)
                if (Hash(Path.Combine(game, item.Key)) != item.Value)
                    throw new InvalidOperationException("DLL изменён после установки: " + item.Key);
            foreach (var item in state.ModifiedDats)
                if (Hash(Path.Combine(game, item.Key)) != item.Value)
                    throw new InvalidOperationException("DAT изменён после установки: " + item.Key);
            foreach (string name in IndexFiles)
                File.Copy(Path.Combine(backup, name), Path.Combine(game, name), true);
            foreach (var item in state.ModifiedDats)
            {
                string target = Path.Combine(game, item.Key);
                if (state.DatLengthsBefore.ContainsKey(item.Key))
                    using (var file = File.OpenWrite(target)) file.SetLength(0);
                else File.Delete(target);
            }
            string mod = ModPath(game);
            if (Path.GetFullPath(mod).StartsWith(Path.GetFullPath(Path.Combine(game, "mods")) + Path.DirectorySeparatorChar,
                                                  StringComparison.OrdinalIgnoreCase)) Directory.Delete(mod, true);
            foreach (var item in state.OwnedDlls) File.Delete(Path.Combine(game, item.Key));
            state.Status = "restored";
            SaveState(game, state);
        }
        if (deleteBackup)
        {
            if (state.Status != "restored") throw new InvalidOperationException("Восстановление не завершено.");
            foreach (string name in IndexFiles)
                if (Hash(Path.Combine(backup, name)) != state.Original[name])
                    throw new InvalidOperationException("Резервная копия изменилась.");
            Directory.Delete(backup, true);
        }
    }

    internal static string? ManagedPhase(string game) => ReadState(game)?.Status;
    internal static bool HasLegacyMod(string game) => Directory.Exists(ModPath(game)) || Directory.Exists(PreviousModPath(game));
}

internal sealed class MainForm : Form
{
    private readonly TextBox path = new();
    private readonly Label status = new();
    private readonly DarkButton[] buttons = new DarkButton[4];
    private readonly string settingsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                                                         "RuVoiceInstaller", "game-path.txt");

    internal MainForm()
    {
        Text = "Голоса Эмбервейла — управление модом";
        ClientSize = new Size(760, 540);
        MinimumSize = new Size(440, 320);
        AutoScaleMode = AutoScaleMode.Dpi;
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = new Font("Segoe UI", 10);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Theme.DarkTitleBar(this);

        var viewport = new Panel { Dock = DockStyle.Fill, AutoScroll = true, BackColor = Theme.Background };
        Controls.Add(viewport);
        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Top, AutoSize = true, AutoSizeMode = AutoSizeMode.GrowAndShrink,
            ColumnCount = 1, Padding = new Padding(24, 16, 24, 18), BackColor = Theme.Background
        };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        viewport.Controls.Add(layout);
        void Add(Control control, int top = 0, int bottom = 0)
        {
            control.Dock = DockStyle.Top;
            control.Margin = new Padding(0, top, 0, bottom);
            layout.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            layout.Controls.Add(control, 0, layout.RowCount++);
        }
        Label NewLabel(string text, float size, bool bold = false, Color? color = null)
            => new()
            {
                Text = text, AutoSize = true, BackColor = Color.Transparent,
                ForeColor = color ?? Theme.Text,
                Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular)
            };
        var heading = NewLabel("РУССКАЯ ОЗВУЧКА", 21, true);
        var subtitle = NewLabel("Голоса Эмбервейла · управление модом Enshrouded", 10, color: Theme.Muted);
        var folderLabel = NewLabel("Папка игры", 11, true);
        var hint = NewLabel("Укажите папку, внутри которой лежит enshrouded.exe. Сам файл выбирать не нужно.", 9, color: Theme.Muted);
        Add(heading, bottom: 2);
        Add(subtitle, bottom: 18);
        Add(folderLabel, bottom: 3);
        Add(hint, bottom: 11);

        var inputRow = new TableLayoutPanel { AutoSize = true, ColumnCount = 2, RowCount = 1 };
        inputRow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        inputRow.ColumnStyles.Add(new ColumnStyle(SizeType.AutoSize));
        var inputFrame = new Panel { Height = 44, BackColor = Theme.Input, Dock = DockStyle.Fill, Margin = new Padding(0, 0, 8, 0) };
        path.Dock = DockStyle.Fill;
        path.Margin = new Padding(8, 8, 8, 6);
        path.BackColor = Theme.Input;
        path.ForeColor = Theme.Text;
        path.BorderStyle = BorderStyle.None;
        path.Text = File.Exists(settingsPath) ? File.ReadAllText(settingsPath).Trim() : FindGame();
        path.TextChanged += (_, _) => UpdateButtons();
        inputFrame.Controls.Add(path);
        var browse = new DarkButton { Text = "Выбрать папку", Height = 44, Width = 154, Margin = Padding.Empty };
        browse.Click += (_, _) =>
        {
            using var dialog = new DarkFolderPicker(path.Text.Trim());
            if (dialog.ShowDialog(this) == DialogResult.OK) path.Text = dialog.SelectedPath;
        };
        inputRow.Controls.Add(inputFrame, 0, 0);
        inputRow.Controls.Add(browse, 1, 0);
        Add(inputRow, bottom: 18);

        var card = new TableLayoutPanel
        {
            AutoSize = true, ColumnCount = 1, Padding = new Padding(15, 11, 15, 12),
            BackColor = Theme.Surface
        };
        card.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        card.Controls.Add(NewLabel("СОСТОЯНИЕ", 8, true, Theme.Muted), 0, 0);
        status.AutoSize = true;
        status.Margin = new Padding(0, 5, 0, 0);
        status.ForeColor = Theme.Text;
        status.BackColor = Color.Transparent;
        status.Text = "Нажмите «Проверить состояние».";
        card.Controls.Add(status, 0, 1);
        Add(card, bottom: 16);

        string[] labels = ["Установить мод", "Проверить состояние", "Отключить · копию сохранить", "Удалить мод и копию"];
        Action<string>[] actions = [Operations.Install, p => { Operations.Status(p); },
                                    p => Operations.Restore(p, false), p => Operations.Restore(p, true)];
        var buttonGrid = new TableLayoutPanel { AutoSize = true, ColumnCount = 2, RowCount = 2 };
        for (int i = 0; i < 4; ++i)
        {
            int index = i;
            buttons[i] = new DarkButton
            {
                Text = labels[i], Height = 48, Dock = DockStyle.Fill,
                Margin = new Padding(0, 0, 8, 8), Accent = i == 0, Destructive = i == 3
            };
            buttons[i].Click += async (_, _) => await Execute(labels[index], actions[index]);
        }
        void LayoutButtons()
        {
            int available = Math.Max(1, viewport.ClientSize.Width - 48);
            int required = buttons.Max(b => TextRenderer.MeasureText(b.Text, b.Font).Width + 36);
            bool twoColumns = available >= required * 2 + 12;
            buttonGrid.SuspendLayout();
            buttonGrid.Controls.Clear();
            buttonGrid.ColumnStyles.Clear();
            buttonGrid.RowStyles.Clear();
            buttonGrid.ColumnCount = twoColumns ? 2 : 1;
            buttonGrid.RowCount = twoColumns ? 2 : 4;
            for (int i = 0; i < buttonGrid.ColumnCount; i++)
                buttonGrid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100f / buttonGrid.ColumnCount));
            for (int i = 0; i < buttonGrid.RowCount; i++)
                buttonGrid.RowStyles.Add(new RowStyle(SizeType.AutoSize));
            for (int i = 0; i < buttons.Length; i++)
            {
                buttons[i].Height = Math.Max(48, buttons[i].Font.Height + 20);
                buttonGrid.Controls.Add(buttons[i], twoColumns ? i % 2 : 0, twoColumns ? i / 2 : i);
            }
            buttonGrid.ResumeLayout();
            int textWidth = Math.Max(100, available - 32);
            foreach (var label in new[] { heading, subtitle, folderLabel, hint, status })
                label.MaximumSize = new Size(textWidth, 0);
        }
        viewport.Resize += (_, _) => LayoutButtons();
        Add(buttonGrid, bottom: 12);
        UpdateButtons();
        Add(NewLabel("F3 в игре: русская озвучка · 525 страниц и 593 реплики персонажей", 9, color: Theme.Good), bottom: 7);
        Add(NewLabel("Журнал диагностики: ru_voice_installer.log в папке игры", 9, color: Theme.Muted), bottom: 7);
        var footer = new FlowLayoutPanel { AutoSize = true, WrapContents = true, BackColor = Theme.Background };
        footer.Controls.Add(NewLabel("Разработчик: ", 9, color: Theme.Muted));
        var developer = new LinkLabel
        {
            Text = "Daber (Hypeber)", AutoSize = true,
            LinkColor = Color.FromArgb(164, 174, 255), ActiveLinkColor = Theme.Text,
            VisitedLinkColor = Color.FromArgb(164, 174, 255), BackColor = Color.Transparent
        };
        developer.LinkClicked += (_, _) =>
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("https://github.com/Daber-devNull")
            { UseShellExecute = true });
        footer.Controls.Add(developer);
        var about = new LinkLabel
        {
            Text = "О программе", AutoSize = true, Margin = new Padding(16, 0, 0, 0),
            LinkColor = Theme.Muted, ActiveLinkColor = Theme.Text,
            VisitedLinkColor = Theme.Muted, BackColor = Color.Transparent
        };
        about.LinkClicked += (_, _) => Theme.ShowAbout(this);
        footer.Controls.Add(about);
        Add(footer);
        LayoutButtons();
        Shown += async (_, _) =>
        {
            if (Directory.Exists(path.Text.Trim()))
            {
                try { status.Text = await Task.Run(() => DiagnosticLog.Run(path.Text.Trim(), "status", () => Operations.Status(path.Text.Trim()))); }
                catch (Exception error) { status.Text = error.Message; }
            }
        };
    }

    private async Task Execute(string label, Action<string> action)
    {
        foreach (var button in buttons) button.Enabled = false;
        status.Text = label + "…";
        try
        {
            string game = Path.GetFullPath(path.Text.Trim());
            Directory.CreateDirectory(Path.GetDirectoryName(settingsPath)!);
            File.WriteAllText(settingsPath, game);
            await Task.Run(() => DiagnosticLog.Run(game, label, () => { action(game); return true; }));
            status.Text = await Task.Run(() => DiagnosticLog.Run(game, "status", () => Operations.Status(game)));
        }
        catch (Exception error)
        {
            status.Text = "Действие не завершено: " + error.Message + " Журнал: ru_voice_installer.log";
            Theme.ShowError(this, error.Message);
        }
        finally { foreach (var button in buttons) button.Enabled = true; }
        UpdateButtons();
    }

    private void UpdateButtons()
    {
        if (buttons.Any(button => button is null)) return;
        string game = path.Text.Trim();
        string? phase = Directory.Exists(game) ? Operations.ManagedPhase(game) : null;
        buttons[0].Enabled = (phase is null or "restored") && !Operations.HasLegacyMod(game);
        buttons[2].Enabled = phase == "installed";
        buttons[3].Enabled = phase is "installed" or "restored";
    }

    private static string FindGame()
    {
        for (DirectoryInfo? directory = new(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName, "enshrouded.exe"))) return directory.FullName;
        string[] common = [@"C:\Program Files (x86)\Steam\steamapps\common\Enshrouded"];
        return common.FirstOrDefault(x => File.Exists(Path.Combine(x, "enshrouded.exe"))) ?? "";
    }
}

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        if (args.Length == 2 && args[0] is "--install" or "--restore" or "--diagnose")
        {
            try
            {
                if (args[0] == "--install") DiagnosticLog.Run(args[1], "cli install", () => { Operations.Install(args[1]); return true; });
                else if (args[0] == "--restore") DiagnosticLog.Run(args[1], "cli restore", () => { Operations.Restore(args[1], false); return true; });
                else Console.WriteLine(DiagnosticLog.Run(args[1], "cli diagnose", () => Operations.Status(args[1])));
            }
            catch (Exception error)
            {
                Console.Error.WriteLine(error.Message);
                Environment.ExitCode = 1;
            }
            return;
        }
        ApplicationConfiguration.Initialize();
        using var singleInstance = new Mutex(true, @"Local\EnshroudedRuVoiceInstaller", out bool createdNew);
        if (!createdNew)
        {
            Theme.ShowError(null, "Установщик уже открыт. Вернитесь к первому окну.");
            return;
        }
        Application.Run(new MainForm());
    }
}
