/* Version-pinned Russian voice redirection. Loaded by a native DLL proxy. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <wchar.h>
#include "MinHook.h"
#include "guid_map.h"

#define RVA_VOICE_PLAY_A 0x1214680u
#define RVA_VOICE_PLAY_B 0x1214880u
#define RVA_SOUND_PLAY   0x1051a40u

static const unsigned char kExeSha256[32] = {
    0x82,0xe5,0x02,0x0a,0x87,0x36,0x34,0x8c,
    0xd0,0x37,0x4f,0x00,0x4b,0x2f,0x5e,0x5e,
    0xf4,0x56,0xb5,0xbd,0x27,0xaa,0x54,0x20,
    0xdf,0x34,0xc7,0xdd,0x24,0x1c,0xfe,0xeb
};

typedef void (*VoiceA)(void *, unsigned char *, void *);
typedef void (*VoiceB)(void *, unsigned char *, void *);
typedef uint32_t (*SoundPlay)(void *, uint32_t, uint32_t, const GUID *, void *);
static VoiceA original_voice_a;
static VoiceB original_voice_b;
static SoundPlay original_sound_play;
static DWORD tls_russian = TLS_OUT_OF_INDEXES;
static HMODULE self_module;
static volatile LONG saw_russian_language;
static volatile LONG saw_other_language;
static volatile LONG saw_russian_substitution;
static volatile LONG force_russian;
static HWND status_window;
static HFONT status_font;

static LRESULT CALLBACK status_window_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam) {
    (void)wparam;
    (void)lparam;
    if (message == WM_NCHITTEST) return HTTRANSPARENT;
    if (message == WM_ERASEBKGND) return 1;
    if (message == WM_PAINT) {
        PAINTSTRUCT paint;
        HDC dc = BeginPaint(window, &paint);
        RECT area;
        GetClientRect(window, &area);
        HBRUSH background = CreateSolidBrush(RGB(14, 29, 35));
        FillRect(dc, &area, background);
        DeleteObject(background);
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, RGB(138, 238, 182));
        HFONT previous = (HFONT)SelectObject(dc, status_font);
        DrawTextW(dc, L"РУ ОЗВУЧКА: ВКЛ", -1, &area,
                  DT_CENTER | DT_VCENTER | DT_SINGLELINE);
        SelectObject(dc, previous);
        EndPaint(window, &paint);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

static HWND create_status_window(void) {
    WNDCLASSW window_class = {0};
    window_class.lpfnWndProc = status_window_proc;
    window_class.hInstance = self_module;
    window_class.lpszClassName = L"EnshroudedRussianVoiceStatus";
    if (!RegisterClassW(&window_class)) return NULL;
    status_font = CreateFontW(12, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                              DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                              CLEARTYPE_QUALITY, DEFAULT_PITCH, L"Segoe UI");
    HWND window = CreateWindowExW(WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT |
                                  WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                                  window_class.lpszClassName, L"Russian voice status", WS_POPUP,
                                  0, 0, 184, 22, NULL, NULL, self_module, NULL);
    if (window) SetLayeredWindowAttributes(window, 0, 190, LWA_ALPHA);
    return window;
}

static void show_status_window(int enabled) {
    if (!status_window) return;
    if (!enabled) {
        ShowWindow(status_window, SW_HIDE);
        return;
    }
    RECT game_rect = {0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
    HWND foreground = GetForegroundWindow();
    DWORD process = 0;
    if (foreground && GetWindowThreadProcessId(foreground, &process) &&
        process == GetCurrentProcessId()) GetWindowRect(foreground, &game_rect);
    SetWindowPos(status_window, HWND_TOPMOST, game_rect.right - 194,
                 game_rect.top + 3, 184, 22,
                 SWP_NOACTIVATE | SWP_SHOWWINDOW);
    InvalidateRect(status_window, NULL, TRUE);
}

static void log_line(const char *message) {
    wchar_t path[MAX_PATH];
    DWORD count = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (!count || count >= MAX_PATH - 32) return;
    wchar_t *slash = wcsrchr(path, L'\\');
    if (!slash) return;
    wcscpy(slash + 1, L"ru_voice_runtime.log");
    HANDLE file = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return;
    DWORD written;
    WriteFile(file, message, (DWORD)strlen(message), &written, NULL);
    WriteFile(file, "\r\n", 2, &written, NULL);
    CloseHandle(file);
}

static int verify_executable(void) {
    wchar_t path[MAX_PATH];
    DWORD count = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (!count || count >= MAX_PATH) return 0;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) return 0;
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    unsigned char buffer[65536];
    unsigned char digest[32];
    DWORD read_count;
    int ok = 0;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0) goto done;
    if (BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) < 0) goto done;
    while (ReadFile(file, buffer, sizeof(buffer), &read_count, NULL) && read_count) {
        if (BCryptHashData(hash, buffer, read_count, 0) < 0) goto done;
    }
    if (GetLastError() != ERROR_HANDLE_EOF && read_count != 0) goto done;
    if (BCryptFinishHash(hash, digest, sizeof(digest), 0) < 0) goto done;
    ok = memcmp(digest, kExeSha256, sizeof(digest)) == 0;
done:
    if (hash) BCryptDestroyHash(hash);
    if (algorithm) BCryptCloseAlgorithmProvider(algorithm, 0);
    CloseHandle(file);
    return ok;
}

static uint32_t sound_play_hook(void *manager, uint32_t zero, uint32_t id,
                                const GUID *requested, void *options) {
    if (requested && tls_russian != TLS_OUT_OF_INDEXES && TlsGetValue(tls_russian)) {
        for (size_t i = 0; i < VOICE_GUID_MAP_COUNT; ++i) {
            if (memcmp(requested, &kVoiceGuidMap[i].english, sizeof(GUID)) == 0) {
                if (InterlockedCompareExchange(&saw_russian_substitution, 1, 0) == 0)
                    log_line("Russian sound-container substitution confirmed");
                return original_sound_play(manager, zero, id, &kVoiceGuidMap[i].russian, options);
            }
        }
    }
    return original_sound_play(manager, zero, id, requested, options);
}

static void voice_a_hook(void *voice, unsigned char *state, void *options) {
    void *previous = TlsGetValue(tls_russian);
    if (state) {
        int language = *(int *)(state + 0x700);
        if (language == 9 || InterlockedCompareExchange(&force_russian, 0, 0)) {
            if (InterlockedCompareExchange(&saw_russian_language, 1, 0) == 0) {
                char message[96];
                sprintf_s(message, sizeof(message), "Russian routing requested; game language=%d", language);
                log_line(message);
            }
            TlsSetValue(tls_russian, (void *)1);
        } else if (InterlockedCompareExchange(&saw_other_language, 1, 0) == 0) {
            char message[96];
            sprintf_s(message, sizeof(message), "Voice playback received other language=%d", language);
            log_line(message);
        }
    }
    original_voice_a(voice, state, options);
    TlsSetValue(tls_russian, previous);
}

static void voice_b_hook(void *voice, unsigned char *state, void *options) {
    void *previous = TlsGetValue(tls_russian);
    if (state) {
        int language = *(int *)(state + 0x700);
        if (language == 9 || InterlockedCompareExchange(&force_russian, 0, 0)) {
            if (InterlockedCompareExchange(&saw_russian_language, 1, 0) == 0) {
                char message[96];
                sprintf_s(message, sizeof(message), "Russian routing requested; game language=%d", language);
                log_line(message);
            }
            TlsSetValue(tls_russian, (void *)1);
        } else if (InterlockedCompareExchange(&saw_other_language, 1, 0) == 0) {
            char message[96];
            sprintf_s(message, sizeof(message), "Voice playback received other language=%d", language);
            log_line(message);
        }
    }
    original_voice_b(voice, state, options);
    TlsSetValue(tls_russian, previous);
}

static DWORD WINAPI install_hooks(void *unused) {
    (void)unused;
    if (!verify_executable()) {
        log_line("Unknown enshrouded.exe SHA-256; Russian voice hooks disabled");
        return 0;
    }
    unsigned char *base = (unsigned char *)GetModuleHandleW(NULL);
    if (!base || MH_Initialize() != MH_OK) {
        log_line("MinHook initialization failed");
        return 0;
    }
    tls_russian = TlsAlloc();
    if (tls_russian == TLS_OUT_OF_INDEXES) {
        log_line("TLS allocation failed");
        return 0;
    }
    if (MH_CreateHook(base + RVA_VOICE_PLAY_A, voice_a_hook, (void **)&original_voice_a) != MH_OK ||
        MH_CreateHook(base + RVA_VOICE_PLAY_B, voice_b_hook, (void **)&original_voice_b) != MH_OK ||
        MH_CreateHook(base + RVA_SOUND_PLAY, sound_play_hook, (void **)&original_sound_play) != MH_OK ||
        MH_EnableHook(MH_ALL_HOOKS) != MH_OK) {
        MH_DisableHook(MH_ALL_HOOKS);
        log_line("Voice hook installation failed");
        return 0;
    }
    log_line("Russian voice hooks active for pinned Enshrouded build");
    status_window = create_status_window();
    if (!status_window) log_line("Russian voice status overlay unavailable");
    if (RegisterHotKey(NULL, 0x5255, MOD_NOREPEAT, VK_F3)) {
        log_line("Russian voice toggle: F3");
        MSG message;
        while (GetMessageW(&message, NULL, 0, 0) > 0) {
            if (message.message == WM_HOTKEY && message.wParam == 0x5255) {
                DWORD foreground_process = 0;
                GetWindowThreadProcessId(GetForegroundWindow(), &foreground_process);
                if (foreground_process != GetCurrentProcessId()) continue;
                LONG enabled = InterlockedCompareExchange(&force_russian, 0, 0) ? 0 : 1;
                InterlockedExchange(&force_russian, enabled);
                show_status_window(enabled);
                log_line(enabled ? "Russian voice ON (F3)" : "Russian voice OFF (F3)");
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        UnregisterHotKey(NULL, 0x5255);
    } else {
        log_line("Russian voice F3 hotkey registration failed");
    }
    if (status_window) DestroyWindow(status_window);
    if (status_font) DeleteObject(status_font);
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE module, DWORD reason, LPVOID reserved) {
    (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        self_module = module;
        DisableThreadLibraryCalls(module);
        HANDLE worker = CreateThread(NULL, 0, install_hooks, NULL, 0, NULL);
        if (worker) CloseHandle(worker);
    }
    return TRUE;
}
