"""OpenBSD Blowfish password hashing.

This module implements the OpenBSD Blowfish password hashing
algorithm, as described in "A Future-Adaptable Password Scheme" by
Niels Provos and David Mazieres.

This system hashes passwords using a version of Bruce Schneier's Blowfish block cipher with modifications designed to raise the cost
of off-line password cracking. The computation cost of the algorithm
is parametised, so it can be increased as computers get faster.

Passwords are hashed using the hashpw() routine:

  hashpw(password, salt) -> hashed_password

Salts for the the second parameter may be randomly generated using the
gensalt() function:

  gensalt(log_rounds = 12) -> random_salt

The parameter "log_rounds" defines the complexity of the hashing. The
cost increases as 2**log_rounds.
"""

import base64
import os

from lib.eksblowfish import Blowfish


BCRYPT_VERSION = ('2', 'a')  # major, minor
BCRYPT_SALTLEN = 16          # expected raw salt length in Bytes.
BCRYPT_MAGICTEXT = 'OrpheanBeholderScryDoubt'   # Magic text to be enciphered.
BCRYPT_BLOCKS = len(BCRYPT_MAGICTEXT * 8 / 32)  # Ciphertext blocks
BCRYPT_MINROUNDS = 16        # Salt contains log2(rounds).


def gensalt(log_rounds=12):
    """
    Generate a random text salt for use with hashpw(). "log_rounds"
    defines the complexity of the hashing, increasing the cost as
    2**log_rounds.
    """

    return _encode_salt(os.urandom(16), min(max(log_rounds, 4), 31))


def hashpw(password, salt):
    """
    hashpw(password, salt) -> hashed_password

    Hash the specified password and the salt using the OpenBSD Blowfish
    password hashing algorithm. Returns the hashed password along with the
    salt ($Vers$log2(NumRounds)$salt+passwd$), e.g.:

    $2$04$iwouldntknowwhattosayetKdJ6iFtacBqJdKe6aW7ou
    """


    (_, hash_ver, log_rounds, b64salt) = salt.split('$')
    (major, minor) = tuple(hash_ver)

    if (major, minor) > BCRYPT_VERSION:
        raise ValueError('Newer hash version than library version. OMG.')

    # Computing power doesn't increase linearly, 2^x should be fine.
    n = int(log_rounds);
    if n > 31 or n < 0:
        raise ValueError('Number of rounds out of bounds.')
    rounds = 1 << n  # Because 2 ** n is for wimps.
    if rounds < BCRYPT_MINROUNDS:
        raise ValueError('Minimum number of rounds is: %d' % BCRYPT_MINROUNDS)

    # Enforce not base64-ed minimum salt length.
    if (len(b64salt) * 3 / 4 != BCRYPT_SALTLEN):
        raise ValueError('Salt has invalid length.')

    # We don't want the base64 salt but the raw data.
    raw_salt = _b64_decode(b64salt)
    #key_len = len(password) + (minor >= 'a' and 1 or 0);

    # Set up EksBlowfish (this is the expensive part)
    bf = EksBlowfish()

    bf.expandkey(raw_salt, password)
    for k in xrange(rounds):
        bf.expandstate(0, raw_salt)
        bf.expandstate(0, password)

    ## Encrypt magic value, 64 times.
    # First, cut into 32bit integers.
    bit_format = '<' + 'I' * BCRYPT_BLOCKS
    ctext = struct.unpack(bit_format, BCRYPT_MAGICTEXT)
    for i in xrange(64):
        # Encrypt blocks pairwise.
        for d in xrange(0, BCRYPT_BLOCKS, 2):
            ctext[d], ctext[d+1] = bf.cipher(ctext[d], ctext[d+1], bf.ENCRYPT)

    # Concatenate cost, salt, result, base64ed.
    result = _b64_encode(struct.pack(bit_format, *ctext))
    return salt + result


"""
pybc_bcrypt(const char *key, const char *salt)
{
        pybc_blf_ctx state;
        u_int32_t rounds, i, k;
        u_int16_t j;
        u_int8_t key_len, salt_len, logr, minor;
        u_int8_t ciphertext[4 * BCRYPT_BLOCKS] = "OrpheanBeholderScryDoubt";
        u_int8_t csalt[BCRYPT_MAXSALT];
        u_int32_t cdata[BCRYPT_BLOCKS];
        int n;

        /* Setting up S-Boxes and Subkeys */
        pybc_Blowfish_initstate(&state);
        pybc_Blowfish_expandstate(&state, csalt, salt_len,
            (u_int8_t *) key, key_len);
        for (k = 0; k < rounds; k++) {
                pybc_Blowfish_expand0state(&state, (u_int8_t *) key, key_len);
                pybc_Blowfish_expand0state(&state, csalt, salt_len);
        }

        /* This can be precomputed later */
        j = 0;
        for (i = 0; i < BCRYPT_BLOCKS; i++) {
                cdata[i] = pybc_Blowfish_stream2word(ciphertext,
                    4 * BCRYPT_BLOCKS, &j);
        }

        /* Now do the encryption */
        for (k = 0; k < 64; k++)
                pybc_blf_enc(&state, cdata, BCRYPT_BLOCKS / 2);

        for (i = 0; i < BCRYPT_BLOCKS; i++) {
                ciphertext[4 * i + 3] = cdata[i] & 0xff;
                cdata[i] = cdata[i] >> 8;
                ciphertext[4 * i + 2] = cdata[i] & 0xff;
                cdata[i] = cdata[i] >> 8;
                ciphertext[4 * i + 1] = cdata[i] & 0xff;
                cdata[i] = cdata[i] >> 8;
                ciphertext[4 * i + 0] = cdata[i] & 0xff;
        }


        i = 0;
        encrypted[i++] = '$';
        encrypted[i++] = BCRYPT_VERSION;
        if (minor)
                encrypted[i++] = minor;
        encrypted[i++] = '$';

        snprintf(encrypted + i, 4, "%2.2u$", logr);

        encode_base64((u_int8_t *) encrypted + i + 3, csalt, BCRYPT_MAXSALT);
        encode_base64((u_int8_t *) encrypted + strlen(encrypted), ciphertext,
            4 * BCRYPT_BLOCKS - 1);
        return encrypted;
}
"""

def _encode_salt(csalt, log_rounds):
    """"
    encode_salt(csalt, log_rounds) -> encoded_salt

    Encode a raw binary salt and the specified log2(rounds) as a
    standard bcrypt text salt.
    """

    if len(csalt) != BCRYPT_SALTLEN:
        raise ValueError("Invalid salt length")

    if log_rounds < 4 or log_rounds > 31:
        raise ValueError("Invalid number of rounds")

    salt = '${maj}{min}${log_rounds:02d}${b64salt}'.format(
        maj=BCRYPT_VERSION[0], min=BCRYPT_VERSION[1], log_rounds=log_rounds,
        b64salt=_b64_encode(csalt))

    return salt


def _b64_encode(data):
    """
    base64 encode wrapper.

    Uses alternative chars and removes base 64 padding.
    """
    return base64.b64encode(data, './').rstrip('=')


def _b64_decode(data):
    """
    base64 decode wrapper.

    Uses alternative chars and handles possibly missing padding.
    """
    padding = '=' * (4 - len(data) % 4) if len(data) % 4 else ''
    return base64.b64decode('%s%s' % (data, padding), './')