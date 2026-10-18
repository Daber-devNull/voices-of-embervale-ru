using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
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

internal static class Operations
{
    internal const string ExeHash = "82e5020a8736348cd0374f004b2f5e5ef456b5bd27aa5420df34c7dd241cfeeb";
    internal const string KfcHash = "a030bcdb58a089f84dd00fb0c6939fd492a2dff440bcb5b63f70efc44b1b9320";
    internal const string ResourcesHash = "cf47db07ae2a959c22e88c661c8e7318a283e3ea063b7a74570ada6a5af9467b";
    private static readonly string[] IndexFiles = ["enshrouded.kfc", "enshrouded.kfc_resources"];
    private static readonly string[] DllFiles = ["dbghelp.dll", "winmm.dll", "shroudtopia.dll"];
    private static readonly JsonSerializerOptions JsonOptions = new() { WriteIndented = true, PropertyNameCaseInsensitive = true };

    internal static string Payload => Path.Combine(AppContext.BaseDirectory, "payload");
    private static string Backup(string game) => Path.Combine(game, ".ru_voice_backup");
    private static string StatePath(string game) => Path.Combine(Backup(game), "state.json");
    private static string ModPath(string game) => Path.Combine(game, "mods", "ru_voice_separate_520");
    private static string Expected(string name) => name == "enshrouded.kfc" ? KfcHash : ResourcesHash;

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
        if (Hash(Path.Combine(game, "enshrouded.exe")) != ExeHash)
            throw new InvalidOperationException("Версия игры не поддерживается. Установщик ничего не изменил.");
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
        if (manifest.Files.Count < 525) throw new InvalidOperationException("Пакет озвучки неполный.");
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
        if (state is null)
        {
            if (Directory.Exists(ModPath(game)))
                return "Найден прежний тестовый мод. Перед установкой пакета требуется его штатный откат.";
            if (IndexFiles.Any(name => !File.Exists(Path.Combine(game, name)) || Hash(Path.Combine(game, name)) != Expected(name)))
                return "Мод не зарегистрирован, но индекс игры изменён. Нужна проверка перед установкой.";
            return "Совместимая игра. Мод не установлен.";
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
        return refreshed
            ? "Русская озвучка установлена: 520 записей. Индекс обновлён загрузчиком при запуске игры."
            : "Русская озвучка установлена: 520 записей, F3 включает и выключает её.";
    }

    internal static void Install(string game)
    {
        CheckClosed();
        CheckGame(game);
        var manifest = VerifyPayload();
        var oldState = ReadState(game);
        if (oldState?.Status == "installed") throw new InvalidOperationException("Мод уже установлен.");
        if (oldState is not null && oldState.Status != "restored")
            throw new InvalidOperationException("Неизвестное состояние резервной копии.");
        foreach (string name in IndexFiles)
            if (Hash(Path.Combine(game, name)) != Expected(name))
                throw new InvalidOperationException("Индекс игры уже изменён другим модом: " + name);
        string mod = ModPath(game), backup = Backup(game);
        if (Directory.Exists(mod)) throw new InvalidOperationException("Папка ru_voice_separate_520 уже существует.");
        if (oldState is null && Directory.Exists(backup))
            throw new InvalidOperationException("Папка .ru_voice_backup уже существует.");
        var state = oldState ?? new InstallState();
        state.GameExeHash = ExeHash;
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
            if (Hash(target) != Expected(name)) throw new InvalidOperationException("Резервная копия не прошла проверку.");
            state.Original[name] = Expected(name);
        }
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
        catch
        {
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
        if (process.ExitCode != 0 || output.Split("RU_VOICE_MAP ").Length - 1 != 520)
            throw new InvalidOperationException("EML не создал 520 записей. " + output[^Math.Min(output.Length, 700)..]);
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
            foreach (string name in IndexFiles)
                if (!File.Exists(Path.Combine(backup, name)) || Hash(Path.Combine(backup, name)) != Expected(name))
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
                if (Hash(Path.Combine(backup, name)) != Expected(name))
                    throw new InvalidOperationException("Резервная копия изменилась.");
            Directory.Delete(backup, true);
        }
    }

    internal static string? ManagedPhase(string game) => ReadState(game)?.Status;
    internal static bool HasLegacyMod(string game) => Directory.Exists(ModPath(game));
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
        ClientSize = new Size(760, 455);
        MinimumSize = new Size(760, 455);
        MaximizeBox = false;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = new Font("Segoe UI", 10);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        Theme.DarkTitleBar(this);
        Controls.Add(Theme.Label("РУССКАЯ ОЗВУЧКА", 28, 22, 690, 42, 22, true));
        Controls.Add(Theme.Label("Голоса Эмбервейла · управление модом Enshrouded", 29, 65, 690, 25,
                                 color: Theme.Muted));
        Controls.Add(Theme.Label("Папка игры", 28, 109, 690, 26, 11, true));
        Controls.Add(Theme.Label("Укажите папку, внутри которой лежит enshrouded.exe. Сам файл выбирать не нужно.",
                                 28, 136, 700, 23, color: Theme.Muted));
        var inputFrame = new Panel { Location = new Point(28, 168), Size = new Size(548, 40), BackColor = Theme.Input };
        path.SetBounds(10, 9, 528, 24);
        path.BackColor = Theme.Input;
        path.ForeColor = Theme.Text;
        path.BorderStyle = BorderStyle.None;
        path.Text = File.Exists(settingsPath) ? File.ReadAllText(settingsPath).Trim() : FindGame();
        path.TextChanged += (_, _) => UpdateButtons();
        inputFrame.Controls.Add(path);
        Controls.Add(inputFrame);
        var browse = new DarkButton { Text = "Выбрать папку", Location = new Point(586, 168), Size = new Size(146, 40) };
        browse.Click += (_, _) =>
        {
            using var dialog = new DarkFolderPicker(path.Text.Trim());
            if (dialog.ShowDialog(this) == DialogResult.OK) path.Text = dialog.SelectedPath;
        };
        Controls.Add(browse);
        var card = new Panel { Location = new Point(28, 229), Size = new Size(704, 66), BackColor = Theme.Surface };
        card.Controls.Add(Theme.Label("СОСТОЯНИЕ", 16, 8, 660, 19, 8, true, Theme.Muted));
        status.Location = new Point(16, 29);
        status.Size = new Size(670, 28);
        status.ForeColor = Theme.Text;
        status.BackColor = Color.Transparent;
        status.Text = "Нажмите «Проверить состояние».";
        card.Controls.Add(status);
        Controls.Add(card);
        string[] labels = ["Установить мод", "Проверить состояние", "Отключить · копию сохранить", "Удалить мод и копию"];
        Action<string>[] actions = [Operations.Install, p => status.Text = Operations.Status(p),
                                    p => Operations.Restore(p, false), p => Operations.Restore(p, true)];
        for (int i = 0; i < 4; ++i)
        {
            int index = i;
            buttons[i] = new DarkButton
            {
                Text = labels[i], Location = new Point(28 + (i % 2) * 357, 314 + (i / 2) * 55),
                Size = new Size(347, 44), Accent = i == 0, Destructive = i == 3
            };
            buttons[i].Click += async (_, _) => await Execute(labels[index], actions[index]);
            Controls.Add(buttons[i]);
        }
        UpdateButtons();
        Controls.Add(Theme.Label("F3 в игре: включить или выключить русскую озвучку · 520 записей",
                                 28, 424, 610, 23, color: Theme.Good));
        var about = new LinkLabel
        {
            Text = "О программе", Location = new Point(650, 424), Size = new Size(90, 23),
            LinkColor = Theme.Muted, ActiveLinkColor = Theme.Text,
            VisitedLinkColor = Theme.Muted, BackColor = Color.Transparent
        };
        about.LinkClicked += (_, _) => Theme.ShowAbout(this);
        Controls.Add(about);
        Shown += async (_, _) =>
        {
            if (Directory.Exists(path.Text.Trim()))
            {
                try { status.Text = await Task.Run(() => Operations.Status(path.Text.Trim())); }
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
            await Task.Run(() => action(game));
            status.Text = Operations.Status(game);
        }
        catch (Exception error)
        {
            status.Text = "Действие не завершено: " + error.Message;
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
    private static void Main()
    {
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
