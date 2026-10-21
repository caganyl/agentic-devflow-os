# İstemci Sınırı ve AI Girdisi Kontrolleri (referans)

Esin kaynağı: msitarzewski/agency-agents `security-ai-generated-code-auditor`
(MIT). Next.js/React ve DevFlow'a uyarlandı, kendi ifadelerimizle.

`adversarial-security-review` §3 ve §4 bu dosyayı, değişiklik frontend
kodu, ortam değişkeni veya LLM çağrısı içeriyorsa uygular. Bu hatalar
özellikle AI ile üretilmiş kodda sık görülür: kod "bitmiş" görünür ama
sır tarayıcıya gider veya kullanıcı girdisi talimata dönüşür.

## 1. Sır tarayıcıya ulaşıyor mu?

```
- [ ] "use client" dosyasında veya onun import ettiği modülde sunucu sırrı
      (API anahtarı, DB bağlantısı, servis anahtarı) var mı?
- [ ] Tarayıcıya gömülen önekli değişkende sır var mı?
      (NEXT_PUBLIC_, VITE_, REACT_APP_ önekleri derleme anında bundle'a girer)
- [ ] Sunucu modülü (DB istemcisi, sır okuyan kod) client bileşenine import
      edilmiş mi? Profilde `server-only` varsa sunucu modüllerinde kullanılıyor mu?
- [ ] Derlenmiş JS bundle'da anahtar kalıbı görünüyor mu? (build çıktısında grep)
```

Ayırt et: tasarım gereği herkese açık anahtarlar (Stripe publishable,
analitik proje anahtarı, Supabase anon gibi) bulgu değildir; gerçek koruma
sunucudaki yetkidir. Yanlış alarm güveni düşürür.

Sızmış sır bulgusu **Critical**'dır ve öneri iki adımdır: koddan kaldır
**ve sağlayıcıda anahtarı yenile (rotate)**. Koddan silmek yetmez; commit
edildiği an ele geçmiş sayılır. Raporda sırrın değeri asla yazılmaz;
yalnızca türü, konumu ve maskelenmiş ilk birkaç karakteri.

## 2. Yetki kararı istemcinin değiştirebildiği alana mı dayanıyor?

```
- [ ] Rol/izin, istek gövdesindeki, header'daki veya kullanıcının kendi
      düzenleyebildiği profil alanındaki bir değerden mi okunuyor?
- [ ] Server Action içinde girdi doğrulaması ve yetki kontrolü var mı?
      (Server Action public bir endpoint'tir)
- [ ] Veritabanı seviyesinde "açık görünen ama herkese izin veren" kural var mı?
      (ör. satır seviyesi güvenlik açık ama koşul her zaman true)
```

## 3. Kullanıcı girdisi LLM talimatına karışıyor mu?

```
- [ ] Güvenilmeyen girdi system prompt'a veya tek bir talimat metnine
      string birleştirme ile ekleniyor mu? (Doğrusu: ayrı user mesajı)
- [ ] Aynı LLM çağrısı hem güvenilmeyen girdi alıyor hem tool/function
      çağırabiliyor mu? → **High**: başarılı injection gerçek eylem tetikler
      (para iadesi, kayıt silme, e-posta gönderme)
- [ ] LLM'in önerdiği tool parametreleri çalıştırılmadan önce sunucuda
      doğrulanıyor mu?
```

## 4. Kanıt kuralı

Her bulgu yanında **nasıl sömürüleceği** ve **düzeltmesi** yazılır
("DevTools'u açan herkes okur; sunucu route'una taşı ve anahtarı yenile").
"Olası sır tespit edildi" gibi kanıtsız bulgu yazılmaz. Belirsiz bir
akışta tahmin yürütme; emin olunmayan durum "doğrulanması gerekiyor"
notuyla Informational olarak kalır. Düzeltildi demek için yeniden tarama
veya test gerekir.
