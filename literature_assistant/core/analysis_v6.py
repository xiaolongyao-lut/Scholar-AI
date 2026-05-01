ciphertext = "*B@m\'+;2kA>>A{xAYCP`Z~M_QQ2:~8IQ\"{1Z!$}HHst`H%v?$hS`pc8-X77M(7]M\'W;Qioi{annq]=\'M)p8fB,[U/s$3Qq+(P%$9[BxEx:fK8W(u.^Y{\'\"6<]a1YO]etO.F[QE~\'Lw"

def rot_cipher(s, n):
    res = ""
    for char in s:
        if 33 <= ord(char) <= 126:
            res += chr(33 + (ord(char) - 33 + n) % 94)
        else:
            res += char
    return res

print("Checking ROT-13 variations of alphanumeric only...")
import string
def rot13(s):
    res = []
    for char in s:
        if 'a' <= char <= 'z':
            res.append(chr((ord(char) - ord('a') + 13) % 26 + ord('a')))
        elif 'A' <= char <= 'Z':
            res.append(chr((ord(char) - ord('A') + 13) % 26 + ord('A')))
        else:
            res.append(char)
    return "".join(res)

print("ROT-13: " + rot13(ciphertext))

print("\n--- Testing base91 if it follows similar pattern ---")
# Base91/85/92 often use a variety of chars.
# Let's try to look for patterns in the original string.
# *B@m'+;2kA>>A{xAYCP`
# Many chars are non-alphanumeric. 
# {xAYCP`Z~M_QQ2:~8IQ"
