# Kimlik ve Yetki Kontrol Listesi (referans)

Esin kaynağı: msitarzewski/agency-agents `engineering-identity-access-engineer`
(MIT). DevFlow'a ve .NET + Next.js yığınına uyarlandı, kendi ifadelerimizle.

`adversarial-security-review` §1 bu dosyayı, değişiklik login, token,
oturum, rol/izin, kiracı (tenant) ayrımı veya hesap kurtarma akışına
dokunuyorsa uygular. Her madde bir bulguya dönüşebilir; kanıt dosya:satır
veya test senaryosudur.

## Sekiz kural

1. **Kendi auth mekanizmanı icat etme.** Özel token formatı, elle yazılmış
   parola hash'i, "basitleştirilmiş" OAuth bulgudur. Beklenen: authorization
   code + PKCE, parola için Argon2id/bcrypt (.NET'te `PasswordHasher<T>` veya
   denetlenmiş kütüphane).
2. **İstemci hiçbir zaman otorite değildir.** Yetki kontrolü her istekte
   sunucuda yapılır. Butonu gizlemek UX'tir, güvenlik değil. .NET'te
   endpoint'te `[Authorize]`/`RequireAuthorization` ve policy; Next.js'te
   Server Action ve Route Handler içinde kontrol.
3. **Yönlendirmeleri saldırgan gözüyle doğrula.** Redirect URI tam eşleşmeli
   bir izin listesiyle kontrol edilir; her callback'te `state`, ID token'da
   `nonce` doğrulanır. Login yakınındaki açık yönlendirme hesap ele
   geçirmedir (Critical).
4. **Kısa ömürlü access, dönen refresh.** Access token dakikalarla ölçülür.
   Refresh token her kullanımda yenilenir; eski bir refresh token tekrar
   gelirse (çalınmış demektir) tüm aile iptal edilir ve olay loglanır.
5. **Kiracı ayrımı veri katmanında.** Tenant ID istek parametresinden değil
   doğrulanmış kimlikten alınır ve sorgu filtresiyle zorlanır (EF Core'da
   global query filter veya repository seviyesinde zorunlu filtre). "Her
   geliştirici hatırlar" bir kontrol değildir.
6. **JWT kimlik taşır, sır taşımaz.** Claim'ler minimumdur; PII veya sır
   konmaz (token'ı tutan herkes okuyabilir). `alg` izin listesiyle doğrulanır
   (`none` kabul edilmez); issuer ve audience sabitlenir. .NET'te
   `TokenValidationParameters`: `ValidAlgorithms`, `ValidateIssuer`,
   `ValidateAudience`, `ValidateLifetime` açık olmalı.
7. **Hesap kurtarma login kadar dikkat ister.** Parola sıfırlama ve MFA
   sıfırlama token'ları kısa ömürlü ve tek kullanımlıktır; yanıtlar
   kullanıcının var olup olmadığını ele vermez; hassas değişiklik ek
   doğrulama ister.
8. **Her auth olayını logla, nedenini kullanıcıya söyleme.** Kullanıcı
   yalnızca "geçersiz kimlik bilgisi" görür. Audit log'a hangi bilginin,
   nereden, kaçıncı denemede başarısız olduğu yazılır (parola veya token
   değeri yazılmaz). Kilitlenme, sıfırlama, SSO ve yetki değişiklikleri
   audit olayıdır.

## Önem rehberi

- Kural 2, 3, 5 ihlali veya `alg` doğrulanmaması: **Critical/High** (blocker)
- Kural 4, 6 (claim'de PII), 7 ihlali: **High/Medium**
- Kural 8 eksikliği: **Medium**; yanıt metninin kullanıcı varlığını ele
  vermesi **Medium**
