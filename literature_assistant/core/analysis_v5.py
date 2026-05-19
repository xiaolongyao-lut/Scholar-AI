import base64
ciphertext = "*B@m\'+;2kA>>A{xAYCP`Z~M_QQ2:~8IQ\"{1Z!$}HHst`H%v?$hS`pc8-X77M(7]M\'W;Qioi{annq]=\'M)p8fB,[U/s$3Qq+(P%$9[BxEx:fK8W(u.^Y{\'\"6<]a1YO]etO.F[QE~\'Lw"

def rot_cipher(s, n):
    res = ""
    for char in s:
        if 33 <= ord(char) <= 126:
            res += chr(33 + (ord(char) - 33 + n) % 94)
        else:
            res += char
    return res

for i in range(1, 94):
    decoded = rot_cipher(ciphertext, i)
    # Search for anything that looks like English or CTF flags
    if any(keyword in decoded.lower() for keyword in ["the", "and", "flag", "this", "secret"]):
        print(f"Shift {i}: {decoded[:100]}")

print("\n--- Try base64 with different charsets ---")
import string
charset = string.ascii_letters + string.digits + "+/"
# Try shifting the ciphertext then b64 decoding
for i in range(1, 94):
    cand = rot_cipher(ciphertext, i)
    # Filter only base64 chars
    b64_only = "".join(c for c in cand if c in charset)
    if len(b64_only) > 100:
        try:
            val = base64.b64decode(b64_only + "==", validate=False)
            if any(k in val.lower() for k in [b"the ", b"and ", b"flag"]):
                print(f"Shift {i} B64: {val}")
        except: pass

print("\n--- Manual analysis ---")
print(f"First 20 chars: {ciphertext[:20]}")
# * B @ m ' + ; 2 k A > > A { x A Y C P `
# Look for common prefixes: flag{, CTF{, etc.
