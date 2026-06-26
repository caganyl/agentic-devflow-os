---
name: managed-delivery-operations
description: Yalnızca scripts/devflow_operations.py üzerinden kontrollü Git operasyonu yapılabileceğini belirtir ve yasak operasyonları engeller.
agent: delivery-lead
triggers:
  - Commit, push veya PR oluşturmadan önce
  - Herhangi bir Git operasyonu planlanırken
  - Delivery teslim aşamasında
---

# Skill: Managed Delivery Operations

## Amaç

Target project'te tüm Git operasyonlarının `scripts/devflow_operations.py`
üzerinden kontrollü olarak yapılmasını güvenceye al. Ham Git komutlarının
yanlışlıkla çalıştırılmasını önle.

## İzin Verilen Operasyonlar

Yalnızca `devflow_operations.py` subcommand'ları üzerinden:

| Subcommand | Açıklama |
|------------|----------|
| `init-target` | .devflow/ workspace başlat (korumalı branch dışında) |
| `create-run` | Yeni delivery run oluştur (korumalı branch dışında) |
| `launch` | Managed run worktree oluştur ve Claude supervisor başlat |
| `status` | Run durumunu göster |
| `prepare-delivery` | Delivery hazırlık doğrulama raporu üret |

## Kesinlikle Yasak Operasyonlar

Aşağıdaki operasyonlar `devflow_operations.py` üzerinden yapılamaz ve
doğrudan çalıştırılamaz:

| Yasak Operasyon | Neden |
|-----------------|-------|
| `git merge` | Main merge insan onayı gerektirir |
| `git push --force` / `git push -f` | Geçmişi yok eder |
| `git branch -D` / `git branch -d` | Başkasının çalışmasını silebilir |
| `git reset --hard` / `--soft` / `--mixed` | Geri alınamaz değişiklik |
| `git checkout -- .` | Uncommitted değişiklikleri yok eder |
| `git restore .` | Uncommitted değişiklikleri yok eder |
| `git clean -f` | Untracked dosyaları kalıcı siler |
| `git push --force-with-lease` | main üzerinde yasak |
| PR merge | İnsan tarafından yapılır |
| Production deploy | Agent yetkisinde değil |
| Database migration (production) | İnsan onayı gerektirir |

## validate_forbidden_git_operation Hakkında Önemli Not

`validate_forbidden_git_operation` bir string doğrulama fonksiyonudur. Delivery
workflow içinde **planlanmış operasyon string'lerini** kontrol eder.

Bu fonksiyon:
- **OS seviyesinde bir git hook DEĞİLDİR.**
- Başka kaynaklarda çalıştırılan git komutlarını yakalamaz veya engellemez.
- Amacı, delivery akışı içinde yanlışlıkla forbidden komut string'i oluşturulmasını tespit etmektir.

```python
# Doğru kullanım: planlanmış bir git komut string'ini doğrula
validate_forbidden_git_operation("git push --force origin main")  # SystemExit(8)
validate_forbidden_git_operation("git merge main")                 # SystemExit(8)

# Fonksiyon yalnızca bu string'i kontrol eder;
# başka bir terminalde çalıştırılan gerçek git komutunu bilmez.
```

Gerçek enforcement mekanizması: korumalı branch'lerde `init-target`,
`create-run` ve `prepare-delivery` subcommand'ları exit code 7 ile reddeder.

## Prosedür

### Launch ile Tam Delivery Akışı

```bash
# 1. Framework tarafından target repo için run worktree oluştur ve Claude supervisor başlat
python3 scripts/devflow_operations.py launch \
  --target PATH \
  --objective "REQ-XXX: kısa açıklama"

# Dry-run ile planı önce kontrol et
python3 scripts/devflow_operations.py launch \
  --target PATH \
  --dry-run
```

`launch` komutu:
- Target çalışma ağacı temiz mi kontrol eder
- Çakışmasız yeni run ID belirler
- `<target-parent>/.devflow-worktrees/<target-name>/run-NNN` altında worktree oluşturur
- Worktree içinde `.devflow/` başlatır ve run state yazar (main checkout'a dokunmaz)
- Plugin build yapar
- Claude'u `--plugin-dir` ile interaktif olarak başlatır (`--print` kullanmaz)

### Delivery Tamamlandıktan Sonra

```bash
# Approval gate doğrulama raporu üret (gerçek Git işlemi yapmaz)
python3 scripts/devflow_operations.py prepare-delivery \
  --target PATH

# Gate'ler geçildi — onay kanıtı doğrulama (yine de gerçek Git işlemi yapmaz)
python3 scripts/devflow_operations.py prepare-delivery \
  --target PATH \
  --confirm-delivery
```

**Bu sürümde `prepare-delivery` hiçbir gerçek Git mutasyonu çalıştırmaz.**
Commit, push ve PR insan tarafından yapılır.

### Delivery Akışı

```
launch (worktree + Claude supervisor)
    ↓
feature branch'te implementation
    ↓
tests passing ✓
    ↓
security review ✓
    ↓
qa sign-off ✓
    ↓
prepare-delivery (doğrulama raporu)
    ↓
prepare-delivery --confirm-delivery (gate doğrulama)
    ↓
İNSAN: PR review + main merge
```

## Run State ve Test Kontrolü

`--confirm-delivery` verilmeden önce şunlar doğrulanmalı:

1. `tests_passing: true` — test suite geçiyor
2. `security_review_complete: true` — security raporu tamamlandı
3. `qa_sign_off: true` — QA acceptance verildi
4. Feature branch'te olunduğu — main/master üzerinde reddedilir

Bu gate'ler `.devflow/runs/RUN-NNN.json` içinde takip edilir.

## Korumalı Branch Sınırları

- `init-target`: main/master üzerinde exit code 7 ile reddedilir; `.devflow/` oluşturulmaz.
- `create-run`: main/master üzerinde exit code 7 ile reddedilir.
- `prepare-delivery`: main/master üzerinde exit code 7 ile reddedilir.
- `launch`: main dahil herhangi bir branch'ten çalıştırılabilir; oluşturduğu worktree yeni run branch'ini kullanır.

## Hata Durumları

- **Main branch (init/create-run/prepare-delivery):** Exit code 7.
- **Kirli çalışma ağacı (launch):** Exit code 11 — commit veya stash yapın.
- **Branch/worktree çakışması (launch):** Exit code 12 — silinmez; bir sonraki launch farklı numara alır.
- **Plugin copy'den launch:** Exit code 5 — framework runner kullanılmalı.
- **Yasak operasyon string'i:** `validate_forbidden_git_operation` exit code 8 verir.
- **Gate geçilmemiş:** `--confirm-delivery` ile bile gate başarısızsa exit code 9.
- **Run yok:** `prepare-delivery` aktif run olmadan exit code 4 verir.
