import base64
ciphertext = "*B@m\'+;2kA>>A{xAYCP`Z~M_QQ2:~8IQ\"{1Z!$}HHst`H%v?$hS`pc8-X77M(7]M\'W;Qioi{annq]=\'M)p8fB,[U/s$3Qq+(P%$9[BxEx:fK8W(u.^Y{\'\"6<]a1YO]etO.F[QE~\'Lw"

def rot47(s):
    res = []
    for c in s:
        v = ord(c)
        if 33 <= v <= 126:
            v = 33 + ((v - 33 + 47) % 94)
        res.append(chr(v))
    return "".join(res)

rotated = rot47(ciphertext)
print(f"ROT47: {rotated}")
try:
    print(f"B64 basic: {base64.b64decode(rotated + '==', validate=False)[:100]}")
except: pass

print("\n--- Testing offsets -50 to 50 ---")
for offset in range(-50, 51):
    res = []
    for c in ciphertext:
        res.append(chr(ord(c) + offset))
    s = "".join(res)
    if "flag" in s.lower() or "{" in s:
        print(f"Offset {offset}: {s}")

print("\n--- Best base64 shift search ---")
import string
b64_chars = set(string.ascii_letters + string.digits + '+/')
for offset in range(-120, 120):
    try:
        s = "".join(chr(ord(c) + offset) for c in ciphertext)
        # Check how many chars are valid base64
        count = sum(1 for c in s if c in b64_chars)
        if count > len(ciphertext) * 0.9:
            print(f"Match! Offset {offset}: {s}")
            try:
                print(f"  Decoded: {base64.b64decode(s + '==', validate=False)}")
            except: pass
    except: pass
