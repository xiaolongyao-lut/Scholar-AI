import base64
ciphertext = "*B@m\'+;2kA>>A{xAYCP`Z~M_QQ2:~8IQ\"{1Z!$}HHst`H%v?$hS`pc8-X77M(7]M\'W;Qioi{annq]=\'M)p8fB,[U/s$3Qq+(P%$9[BxEx:fK8W(u.^Y{\'\"6<]a1YO]etO.F[QE~\'Lw"

def try_decode(s):
    try:
        # Base64 with padding
        for p in ["", "=", "=="]:
            b = base64.b64decode(s + p, validate=False)
            if any(word in b for word in [b"flag", b"FLAG", b"pass", b"user"]):
                return b
    except: pass
    return None

# Try Caesar shift on all characters
for offset in range(-95, 96):
    s = "".join(chr((ord(c) - 32 + offset) % 95 + 32) for c in ciphertext)
    res = try_decode(s)
    if res:
        print(f"Shift {offset}: {res}")

# Try Xor with 0-255
for x in range(256):
    s = "".join(chr(ord(c) ^ x) for c in ciphertext)
    res = try_decode(s)
    if res:
        print(f"Xor {x}: {res}")

# Try to see if it's already readable after some shift
for offset in range(-50, 51):
    s = "".join(chr((ord(c) - 32 + offset) % 95 + 32) for c in ciphertext)
    if any(word in s.lower() for word in ["flag", "ctf", "key", "secret"]):
         print(f"Readable Shift {offset}: {s}")

# Try just printing characters as they are
print("Original printable check:", ciphertext)
