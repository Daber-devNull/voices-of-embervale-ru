using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace RuVoiceInstaller;

internal static class Theme
{
    internal static readonly Color Background = Color.FromArgb(49, 51, 56);
    internal static readonly Color Surface = Color.FromArgb(43, 45, 49);
    internal static readonly Color Input = Color.FromArgb(30, 31, 34);
    internal static readonly Color Text = Color.FromArgb(242, 243, 245);
    internal static readonly Color Muted = Color.FromArgb(181, 186, 193);
    internal static readonly Color Accent = Color.FromArgb(88, 101, 242);
    internal static readonly Color Good = Color.FromArgb(67, 181, 129);
    internal static readonly Color Danger = Color.FromArgb(218, 74, 80);

    [DllImport("dwmapi.dll")]
    private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attribute, ref int value, int size);

    internal static void DarkTitleBar(Form form)
    {
        form.HandleCreated += (_, _) =>
        {
            int enabled = 1;
            _ = DwmSetWindowAttribute(form.Handle, 20, ref enabled, sizeof(int));
        };
    }

    internal static Label Label(string text, int x, int y, int width, int height, int size = 10,
                                bool bold = false, Color? color = null) => new()
    {
        Text = text, Location = new Point(x, y), Size = new Size(width, height),
        ForeColor = color ?? Text, BackColor = Color.Transparent,
        Font = new Font("Segoe UI", size, bold ? FontStyle.Bold : FontStyle.Regular)
    };

    internal static void ShowError(Form? owner, string message)
    {
        using var dialog = new Form
        {
            Text = "Голоса Эмбервейла", StartPosition = FormStartPosition.CenterParent,
            ClientSize = new Size(540, 160), BackColor = Surface, ForeColor = Text,
            Font = new Font("Segoe UI", 10), FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false, MinimizeBox = false, ShowInTaskbar = false
        };
        DarkTitleBar(dialog);
        dialog.Controls.Add(Label(message, 22, 20, 496, 90));
        var ok = new DarkButton { Text = "Понятно", Location = new Point(394, 112), Size = new Size(124, 35), Accent = true };
        ok.Click += (_, _) => dialog.Close();
        dialog.Controls.Add(ok);
        dialog.AcceptButton = ok;
        dialog.ShowDialog(owner);
    }

    internal static void ShowAbout(Form owner)
    {
        using var dialog = new Form
        {
            Text = "О программе", StartPosition = FormStartPosition.CenterParent,
            ClientSize = new Size(500, 160), BackColor = Surface, ForeColor = Text,
            Font = new Font("Segoe UI", 10), FormBorderStyle = FormBorderStyle.FixedDialog,
            MaximizeBox = false, MinimizeBox = false, ShowInTaskbar = false
        };
        DarkTitleBar(dialog);
        dialog.Controls.Add(Label("Голоса Эмбервейла · версия 0.3.1 beta", 20, 18, 460, 30, 12, true));
        dialog.Controls.Add(Label("Иконка: Icons8", 20, 59, 140, 25, color: Muted));
        var credit = new LinkLabel
        {
            Text = "https://icons8.com", Location = new Point(159, 59), Size = new Size(240, 25),
            LinkColor = Color.FromArgb(164, 174, 255), ActiveLinkColor = Text,
            VisitedLinkColor = Color.FromArgb(164, 174, 255), BackColor = Color.Transparent
        };
        credit.LinkClicked += (_, _) =>
            System.Diagnostics.Process.Start(new System.Diagnostics.ProcessStartInfo("https://icons8.com")
            { UseShellExecute = true });
        dialog.Controls.Add(credit);
        var ok = new DarkButton { Text = "Закрыть", Location = new Point(356, 110), Size = new Size(124, 35), Accent = true };
        ok.Click += (_, _) => dialog.Close();
        dialog.Controls.Add(ok);
        dialog.AcceptButton = ok;
        dialog.ShowDialog(owner);
    }
}

internal sealed class DarkButton : Button
{
    internal bool Accent { get; set; }
    internal bool Destructive { get; set; }
    private bool hovered;

    internal DarkButton()
    {
        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint |
                 ControlStyles.OptimizedDoubleBuffer, true);
        Font = new Font("Segoe UI", 10, FontStyle.Bold);
        Cursor = Cursors.Hand;
    }

    protected override void OnMouseEnter(EventArgs e) { hovered = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hovered = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }

    protected override void OnPaint(PaintEventArgs e)
    {
        Color fill = !Enabled ? Color.FromArgb(60, 63, 70)
                   : Destructive ? Theme.Danger
                   : Accent ? Theme.Accent : Color.FromArgb(64, 67, 75);
        if (hovered && Enabled) fill = ControlPaint.Light(fill, 0.12f);
        using var brush = new SolidBrush(fill);
        e.Graphics.FillRectangle(brush, ClientRectangle);
        TextRenderer.DrawText(e.Graphics, Text, Font, ClientRectangle,
            Enabled ? Theme.Text : Theme.Muted,
            TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
    }
}

internal sealed class DarkFolderPicker : Form
{
    private readonly TextBox location = new();
    private readonly ListBox entries = new();
    internal string SelectedPath { get; private set; }

    internal DarkFolderPicker(string initial)
    {
        Text = "Выберите папку с enshrouded.exe";
        ClientSize = new Size(620, 460);
        MinimumSize = new Size(620, 460);
        StartPosition = FormStartPosition.CenterParent;
        BackColor = Theme.Background;
        ForeColor = Theme.Text;
        Font = new Font("Segoe UI", 10);
        Theme.DarkTitleBar(this);
        SelectedPath = Directory.Exists(initial) ? Path.GetFullPath(initial)
            : Environment.GetFolderPath(Environment.SpecialFolder.MyComputer);
        if (!Directory.Exists(SelectedPath)) SelectedPath = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        Controls.Add(Theme.Label("Папка, внутри которой лежит enshrouded.exe", 20, 18, 570, 29, 13, true));
        location.SetBounds(20, 61, 480, 30);
        location.BackColor = Theme.Input;
        location.ForeColor = Theme.Text;
        location.BorderStyle = BorderStyle.FixedSingle;
        location.KeyDown += (_, e) => { if (e.KeyCode == Keys.Enter) { Navigate(location.Text); e.SuppressKeyPress = true; } };
        Controls.Add(location);
        var go = new DarkButton { Text = "Перейти", Location = new Point(509, 60), Size = new Size(91, 31) };
        go.Click += (_, _) => Navigate(location.Text);
        Controls.Add(go);
        entries.SetBounds(20, 105, 580, 270);
        entries.BackColor = Theme.Input;
        entries.ForeColor = Theme.Text;
        entries.BorderStyle = BorderStyle.None;
        entries.Font = new Font("Segoe UI", 10);
        entries.DoubleClick += (_, _) => OpenSelected();
        Controls.Add(entries);
        var up = new DarkButton { Text = "↑ Выше", Location = new Point(20, 394), Size = new Size(105, 39) };
        up.Click += (_, _) => Navigate(Directory.GetParent(SelectedPath)?.FullName ?? SelectedPath);
        Controls.Add(up);
        var cancel = new DarkButton { Text = "Отмена", Location = new Point(354, 394), Size = new Size(112, 39) };
        cancel.Click += (_, _) => { DialogResult = DialogResult.Cancel; Close(); };
        Controls.Add(cancel);
        var select = new DarkButton { Text = "Выбрать папку", Location = new Point(475, 394), Size = new Size(125, 39), Accent = true };
        select.Click += (_, _) => { Navigate(location.Text); if (File.Exists(Path.Combine(SelectedPath, "enshrouded.exe"))) { DialogResult = DialogResult.OK; Close(); } else Theme.ShowError(this, "В этой папке нет enshrouded.exe. Откройте папку самой игры."); };
        Controls.Add(select);
        Navigate(SelectedPath);
    }

    private void OpenSelected()
    {
        if (entries.SelectedItem is string name)
        {
            string path = Path.Combine(SelectedPath, name);
            Navigate(path);
        }
    }

    private void Navigate(string path)
    {
        if (!Directory.Exists(path)) { Theme.ShowError(this, "Папка не найдена: " + path); return; }
        SelectedPath = Path.GetFullPath(path);
        location.Text = SelectedPath;
        entries.BeginUpdate();
        entries.Items.Clear();
        try
        {
            foreach (var child in Directory.GetDirectories(SelectedPath).OrderBy(Path.GetFileName))
                entries.Items.Add(Path.GetFileName(child));
        }
        catch (UnauthorizedAccessException) { }
        entries.EndUpdate();
    }
}
