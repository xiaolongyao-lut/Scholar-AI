import base64
import string

ciphertext = "*B@m\'+;2kA>>A{xAYCP`Z~M_QQ2:~8IQ\"{1Z!$}HHst`H%v?$hS`pc8-X77M(7]M\'W;Qioi{annq]=\'M)p8fB,[U/s$3Qq+(P%$9[BxEx:fK8W(u.^Y{\'\"6<]a1YO]etO.F[QE~\'Lw"

print(f"Length: {len(ciphertext)}")

b64_chars = set(string.ascii_letters + string.digits + '+/=')

def shift_printable(s, n):
    result = []
    for c in s:
        v = ord(c)
        if 33 <= v <= 126:
            v = ((v - 33 + n) % 94) + 33
        result.append(chr(v))
    return "".join(result)

print("=== Best shift ===")
best_n, best_count = 0, len(ciphertext)
for n in range(-93, 100):
    shifted = shift_printable(ciphertext, n)
    cnt = sum(1 for c in shifted if c not in b64_chars)
    if cnt < best_count:
        best_count = cnt
        best_n = n
        
print(f"Best shift: {best_n:+d}, non-B64 remaining: {best_count}")
best_shifted = shift_printable(ciphertext, best_n)
print(f"After shift: {best_shifted}")

print("=== Even/odd split ===")
even_stream = ciphertext[::2]
odd_stream = ciphertext[1::2]
for label, stream in [("Even", even_stream), ("Odd", odd_stream)]:
    for n in range(-93, 100):
        shifted = shift_printable(stream, n)
        cnt = sum(1 for c in shifted if c not in b64_chars)
        if cnt == 0:
            print(f"    {label} CLEAN shift {n:+d} -> {shifted}")
            try:
                dec = base64.b64decode(shifted + "==", validate=False)
                print(f"    B64 decoded: {dec[:50]}")
            except: pass
