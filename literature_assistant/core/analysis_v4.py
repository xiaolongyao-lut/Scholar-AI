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
    if "flag" in decoded.lower():
        print(f"Shift {i}: {decoded}")

# Also try base85
import base64
try:
    print("Trying base85...")
    print(base64.b85decode(ciphertext.encode()))
except Exception as e:
    print(f"B85 error: {e}")

try:
    print("Trying base64 URL safe...")
    # Clean non-b64-url
    url_b64 = "".join(c for c in ciphertext if c in (string.ascii_letters + string.digits + "-_"))
    print(base64.urlsafe_b64decode(url_b64 + "===="))
except: pass
