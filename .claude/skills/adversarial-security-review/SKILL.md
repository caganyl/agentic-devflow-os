---
name: adversarial-security-review
description: Threat modeling, prompt injection, secret exposure, unsafe input, authz/authn, dependency ve veri riskleri için adversarial güvenlik review yapar.
agent: security-red-team
triggers:
  - Implementation tamamlandıktan sonra, release öncesinde
  - AI/LLM feature içeren her implementation
  - Auth/authz değişikliği yapıldığında
  - External veri alınan her özellikte
---

# Skill: Adversarial Security Review

## Amaç

Kötü niyetli veya beklenmedik girdiler karşısında sistemin nasıl davrandığını incele.
Saldırgan bakış açısıyla düşün; sadece "normal kullanım" değil.

## Prosedür

### 1. Authentication & Authorization

```
- [ ] Kimlik doğrulama her endpoint'te zorunlu mu?
- [ ] Rol/permission kontrolleri doğru uygulanmış mı?
- [ ] Token ömrü ve yenileme mekanizması güvenli mi?
- [ ] Privilege escalation mümkün mü?
- [ ] Cross-tenant veri erişimi engellenmiş mi?
```

### 2. Input Validation & Injection

```
- [ ] Tüm kullanıcı girdileri validate ediliyor mu?
- [ ] SQL injection riski var mı? (parametrize query kullanılıyor mu?)
- [ ] Command injection riski var mı?
- [ ] Path traversal riski var mı?
- [ ] XSS: output encode ediliyor mu?
- [ ] CSRF token uygulanmış mı?
```

### 3. Prompt Injection (AI Feature'lar için)

```
- [ ] Kullanıcı girdisi prompt'a doğrudan ekleniyor mu?
- [ ] Sistem prompt'u override edilebilir mi?
- [ ] LLM çıktısı parse edilirken injection riski var mı?
- [ ] Tool/function call parametreleri validate ediliyor mu?
- [ ] Kötü niyetli prompt "ignore previous instructions" denendi mi?
```

### 4. Secret Exposure

```
- [ ] API key, token veya secret kod içinde sabit yazılmış mı?
- [ ] Secret log'a düşüyor mu?
- [ ] Secret response body'de dönüyor mu?
- [ ] .env dosyası .gitignore'da mı?
```

### 5. Data Privacy

```
- [ ] PII loglarda görünüyor mu?
- [ ] PII şifreleniyor mu?
- [ ] Veri minimizasyonu uygulanmış mı?
- [ ] Soft delete mi, hard delete mi? Silme sonrası PII kaldı mı?
```

### 6. Dependency Risks

```
- [ ] Bağımlılıklar güncel mi?
- [ ] Bilinen CVE içeren paket var mı?
- [ ] Güvenilmeyen paket eklendi mi?
```

### 7. SSRF (Server-Side Request Forgery)

```
- [ ] Kullanıcı kontrolünde URL fetch ediliyor mu?
- [ ] İç ağa erişim engellenmiş mi?
- [ ] Allowlist mekanizması var mı?
```

## Bulgu Formatı

```markdown
### Security Finding: [başlık]

**Severity:** Critical / High / Medium / Low / Informational
**Kategori:** Injection / AuthZ / Secret / PII / Dependency / ...
**Etkilenen bileşen:** [dosya veya endpoint]
**Açıklama:** [ne, nasıl sömürülebilir]
**Kanıt:** [kod satırı veya test senaryosu]
**Öneri:** [nasıl düzeltilmeli]
**Blocker mı?:** Evet (Critical/High) / Hayır (Medium/Low)
```

## Review Kararı

- **Critical/High blocker varsa:** Release yapma, düzelt
- **Medium varsa:** Plan içinde takip et, sonraki release öncesi kapat
- **Low/Informational:** Backlog'a ekle
- **Temiz:** Security sign-off ver

## Kesin Sınırlar

- Uygulama kodunu değiştirme; yalnızca rapor üret
- Gerçek saldırı deneme — test ortamı dahil production benzeri sistemlerde
