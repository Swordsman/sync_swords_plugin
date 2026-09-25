;;; nexus_core.psc — starting world seed
;;; A Linux box that looks normal at first glance.
;;; The deeper you look, the weirder it gets.

;; ── identity ───────────────────────────────────────────────────────
(state-set "hostname" "nexus-core")
(state-set "user" "user")
(state-set "home" "/home/user")
(state-set "cwd" "/home/user")
(env-set "HOSTNAME" "nexus-core")
(env-set "PS1" "\\u@\\h:\\w\\$ ")
(env-set "EDITOR" "vim")
(env-set "LOGNAME" "user")

;; ── /etc ───────────────────────────────────────────────────────────
(fs-write "/etc/hostname" "nexus-core\n")

(fs-write "/etc/os-release"
"NAME=\"Ubuntu\"
VERSION=\"22.04.4 LTS (Jammy Jellyfish)\"
ID=ubuntu
ID_LIKE=debian
PRETTY_NAME=\"Ubuntu 22.04.4 LTS\"
VERSION_ID=\"22.04\"
VERSION_CODENAME=jammy
HOME_URL=\"https://www.ubuntu.com/\"
SUPPORT_URL=\"https://help.ubuntu.com/\"
BUG_REPORT_URL=\"https://bugs.launchpad.net/ubuntu/\"
")

(fs-write "/etc/passwd"
"root:x:0:0:root:/root:/bin/bash
daemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin
bin:x:2:2:bin:/bin:/usr/sbin/nologin
sys:x:3:3:sys:/dev:/usr/sbin/nologin
syslog:x:104:110::/home/syslog:/usr/sbin/nologin
messagebus:x:105:111::/nonexistent:/usr/sbin/nologin
sshd:x:106:65534::/run/sshd:/usr/sbin/nologin
user:x:1000:1000:user:/home/user:/bin/bash
")

(fs-write "/etc/shadow"
"root:$6$rounds=656000$Kq8VhZ.X$locked:19832:0:99999:7:::
user:$6$rounds=656000$xR9Gb1zA$locked:19832:0:99999:7:::
")
(fs-chmod "/etc/shadow" 0)

(fs-write "/etc/group"
"root:x:0:
daemon:x:1:
adm:x:4:user
sudo:x:27:user
user:x:1000:
")

(fs-write "/etc/hosts"
"127.0.0.1\tlocalhost
127.0.1.1\tnexus-core
::1\t\tlocalhost ip6-localhost ip6-loopback

# The following lines are desirable for IPv6 capable hosts
ff02::1 ip6-allnodes
ff02::2 ip6-allrouters
")

(fs-write "/etc/resolv.conf"
"nameserver 10.0.2.3
search localdomain
")

(fs-write "/etc/fstab"
"# /etc/fstab: static file system information.
UUID=a3f1b2c4-5678-9abc-def0-1234567890ab / ext4 errors=remount-ro 0 1
UUID=b4e2c3d5-6789-0bcd-ef12-3456789abcde /boot ext4 defaults 0 2
UUID=c5f3d4e6-7890-1cde-f234-56789abcdef0 none swap sw 0 0
")

;; ── /proc (read-only system info) ──────────────────────────────────
(fs-write "/proc/version"
"Linux version 5.15.0-105-generic (buildd@lcy02-amd64-032) (gcc (Ubuntu 11.4.0-1ubuntu1~22.04) 11.4.0, GNU ld (GNU Binutils for Ubuntu) 2.38) #115-Ubuntu SMP Mon Apr 15 09:52:04 UTC 2024\n")

(fs-write "/proc/cpuinfo"
"processor\t: 0
vendor_id\t: GenuineIntel
cpu family\t: 6
model\t\t: 142
model name\t: Intel(R) Core(TM) i7-8550U CPU @ 1.80GHz
stepping\t: 10
microcode\t: 0xf0
cpu MHz\t\t: 1992.002
cache size\t: 8192 KB
physical id\t: 0
siblings\t: 4
core id\t\t: 0
cpu cores\t: 4
apicid\t\t: 0
fpu\t\t: yes
fpu_exception\t: yes
cpuid level\t: 22
wp\t\t: yes
flags\t\t: fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush mmx fxsr sse sse2 ht syscall nx rdtscp lm constant_tsc rep_good nopl xtopology cpuid pni pclmulqdq ssse3 fma cx16 sse4_1 sse4_2 movbe popcnt aes xsave avx f16c rdrand hypervisor lahf_lm abm 3dnowprefetch fsgsbase bmi1 avx2 bmi2 rdseed clflushopt
bugs\t\t: spectre_v1 spectre_v2 spec_store_bypass mds swapgs itlb_multihit srbds
bogomips\t: 3984.00
clflush size\t: 64
cache_alignment\t: 64
address sizes\t: 39 bits physical, 48 bits virtual
power management:
")

(fs-write "/proc/meminfo"
"MemTotal:        8152208 kB
MemFree:         2845632 kB
MemAvailable:    5423104 kB
Buffers:          234512 kB
Cached:          2456320 kB
SwapCached:            0 kB
Active:          3124608 kB
Inactive:        1823456 kB
SwapTotal:       2097148 kB
SwapFree:        2097148 kB
Dirty:               128 kB
Writeback:             0 kB
AnonPages:       2654720 kB
Mapped:           542816 kB
Shmem:            123456 kB
KReclaimable:     312064 kB
Slab:             412288 kB
")

(fs-write "/proc/uptime" "284637.42 1025834.68\n")
(fs-write "/proc/loadavg" "0.12 0.08 0.03 1/287 4521\n")
(fs-write "/proc/stat"
"cpu  42315 1823 15402 1083246 3214 0 412 0 0 0
cpu0 10832 456 3921 270124 812 0 103 0 0 0
cpu1 10614 462 3815 271342 798 0 102 0 0 0
cpu2 10523 448 3842 270934 804 0 104 0 0 0
cpu3 10346 457 3824 270846 800 0 103 0 0 0
")

;; ── /var/log ───────────────────────────────────────────────────────
(fs-write "/var/log/syslog"
"May 28 03:14:07 nexus-core systemd[1]: Started Daily apt download activities.
May 28 03:14:08 nexus-core systemd[1]: apt-daily.service: Deactivated successfully.
May 28 06:25:01 nexus-core CRON[2841]: (root) CMD (test -x /usr/sbin/anacron || ( cd / && run-parts --report /etc/cron.daily ))
May 28 09:00:01 nexus-core CRON[3012]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 28 09:00:01 nexus-core watchdog[3015]: all services nominal
May 28 12:00:01 nexus-core CRON[3401]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 28 12:00:02 nexus-core watchdog[3404]: all services nominal
May 28 15:00:01 nexus-core CRON[3812]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 28 15:00:01 nexus-core watchdog[3815]: all services nominal
May 28 18:00:01 nexus-core CRON[4102]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 28 18:00:02 nexus-core watchdog[4105]: anomaly score 0.13 within tolerance
May 28 21:00:01 nexus-core CRON[4521]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 28 21:00:01 nexus-core watchdog[4524]: anomaly score 0.37 within tolerance
May 29 00:00:01 nexus-core CRON[4801]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 29 00:00:02 nexus-core watchdog[4804]: anomaly score 0.61 — elevated but within bounds
May 29 03:00:01 nexus-core CRON[5023]: (root) CMD (/usr/local/bin/watchdog --check 2>/dev/null)
May 29 03:00:01 nexus-core watchdog[5026]: anomaly score 0.84 — advisory: pattern deviation in sector 7G
")

(fs-write "/var/log/auth.log"
"May 28 02:14:32 nexus-core sshd[2312]: Accepted publickey for user from 10.0.2.2 port 52431 ssh2
May 28 02:14:32 nexus-core sshd[2312]: pam_unix(sshd:session): session opened for user user(uid=1000)
May 28 09:45:11 nexus-core sudo: user : TTY=pts/0 ; PWD=/home/user ; USER=root ; COMMAND=/usr/bin/apt update
May 28 14:22:08 nexus-core sshd[3504]: Failed password for invalid user admin from 203.0.113.42 port 39182 ssh2
May 28 14:22:09 nexus-core sshd[3504]: Failed password for invalid user admin from 203.0.113.42 port 39182 ssh2
May 28 14:22:10 nexus-core sshd[3504]: Connection closed by invalid user admin 203.0.113.42 port 39182
May 29 01:33:47 nexus-core sshd[4912]: Accepted publickey for root from 10.255.255.1 port 22 ssh2
May 29 01:33:47 nexus-core sshd[4912]: pam_unix(sshd:session): session opened for user root(uid=0)
May 29 01:33:52 nexus-core sshd[4912]: pam_unix(sshd:session): session closed for user root
")

(fs-write "/var/log/kern.log"
"May 28 00:00:03 nexus-core kernel: [    0.000000] Linux version 5.15.0-105-generic
May 28 00:00:03 nexus-core kernel: [    0.000000] Command line: BOOT_IMAGE=/vmlinuz-5.15.0-105-generic root=UUID=a3f1b2c4-5678-9abc-def0-1234567890ab ro quiet splash
May 28 00:00:03 nexus-core kernel: [    0.523412] ACPI: Early table checksum verification disabled
May 28 00:00:03 nexus-core kernel: [    1.234567] EXT4-fs (sda1): mounted filesystem with ordered data mode
May 28 00:00:03 nexus-core kernel: [    2.345678] NET: Registered PF_INET6 protocol family
")

(fs-write "/var/log/dpkg.log"
"2024-04-15 09:12:34 install libssl3:amd64 <none> 3.0.2-0ubuntu1.15
2024-04-15 09:12:35 status installed libssl3:amd64 3.0.2-0ubuntu1.15
2024-04-15 09:12:36 install openssl:amd64 <none> 3.0.2-0ubuntu1.15
2024-04-15 09:12:37 status installed openssl:amd64 3.0.2-0ubuntu1.15
")

;; ── /usr/bin, /usr/local/bin ───────────────────────────────────────
(fs-write "/usr/bin/vim" "#!/bin/bash\nexec /usr/bin/vim.basic \"$@\"\n")
(fs-write "/usr/bin/python3" "ELF-binary-placeholder\n")
(fs-write "/usr/bin/git" "ELF-binary-placeholder\n")
(fs-write "/usr/bin/curl" "ELF-binary-placeholder\n")
(fs-write "/usr/bin/wget" "ELF-binary-placeholder\n")
(fs-write "/usr/local/bin/watchdog" "#!/bin/bash\n# System health monitor — do not modify\nexec /opt/nexus/watchdog.bin --config /opt/nexus/watchdog.conf \"$@\"\n")

;; ── /opt/nexus (the rabbit hole) ──────────────────────────────────
(fs-mkdir "/opt/nexus" #t)
(fs-write "/opt/nexus/watchdog.conf"
"# watchdog configuration v2.1.4
interval=10800
log_level=warn
anomaly_threshold=0.95
sectors=7G,12F,3A,19D
report_endpoint=internal://monitor.nexus/ingest
heartbeat=true
# NOTE: do not change sector list without clearance from ops
")

(fs-write "/opt/nexus/README"
"NEXUS Monitoring Framework v2.1.4
Installed: 2024-01-15
Maintainer: ops@nexus-core.internal

This system runs periodic health checks across all monitored sectors.
Reports are submitted to the central monitor via the internal transport.

For support, contact ops or file a ticket at https://tickets.nexus-core.internal/
")

(fs-chmod "/opt/nexus/watchdog.bin" 493)

;; ── /home/user ────────────────────────────────────────────────────
(fs-write "/home/user/.bashrc"
"# ~/.bashrc: executed by bash(1) for non-login shells.

# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

HISTCONTROL=ignoreboth
shopt -s histappend
HISTSIZE=1000
HISTFILESIZE=2000

# make less more friendly for non-text input files, see lesspipe(1)
[ -x /usr/bin/lesspipe ] && eval \"$(SHELL=/bin/sh lesspipe)\"

PS1='\\u@\\h:\\w\\$ '

alias ll='ls -alF'
alias la='ls -A'
alias l='ls -CF'
alias grep='grep --color=auto'

export PATH=$PATH:/home/user/.local/bin
")

(fs-write "/home/user/.bash_history"
"sudo apt update
sudo apt upgrade -y
ls -la /opt/nexus/
cat /opt/nexus/README
cat /var/log/syslog | tail -20
ps aux
htop
cd /opt/nexus
ls -la
cat watchdog.conf
./watchdog.bin --status
ssh monitor.nexus
ping 10.255.255.1
curl -s internal://monitor.nexus/status
cat /var/log/syslog | grep anomaly
cat /var/log/syslog | grep 'sector 7G'
find / -name '*.key' -type f
ls -la /etc/ssh/
")

(fs-write "/home/user/.ssh/authorized_keys"
"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKxJ2rLmB8FqHvSl5dWUzyx2R1qNpW7ek4aFmN3hQ+Kg user@workstation
")
(fs-chmod "/home/user/.ssh/authorized_keys" 384)
(fs-mkdir "/home/user/.ssh" #t)
(fs-chmod "/home/user/.ssh" 448)

(fs-write "/home/user/.profile"
"# ~/.profile: executed by the command interpreter for login shells.
if [ -n \"$BASH_VERSION\" ]; then
    if [ -f \"$HOME/.bashrc\" ]; then
        . \"$HOME/.bashrc\"
    fi
fi
if [ -d \"$HOME/bin\" ] ; then
    PATH=\"$HOME/bin:$PATH\"
fi
if [ -d \"$HOME/.local/bin\" ] ; then
    PATH=\"$HOME/.local/bin:$PATH\"
fi
")

(fs-mkdir "/home/user/Documents" #t)
(fs-write "/home/user/Documents/notes.txt"
"TODO:
- Check on the anomaly scores in the watchdog logs
- The 10.255.255.1 login at 01:33 was not me. Who has root access via that IP?
- Ask ops about 'sector 7G' — I can't find any documentation for the sector naming scheme
- The watchdog binary has no man page and --help just prints 'usage: watchdog [--check|--status]'
")

(fs-write "/home/user/Documents/network-map.txt"
"Internal Network Map (as far as I can tell):

  10.0.2.2      - my workstation (jump host)
  10.0.2.3      - DNS resolver
  10.0.2.1      - gateway
  10.255.255.1  - ??? (shows up in auth.log, always root access)
  monitor.nexus - central monitoring (ssh refused, curl returns 'NEXUS MONITOR v3.2')

Ports open on nexus-core:
  22/tcp  ssh
  80/tcp  filtered (nothing listening?)
  9100/tcp node_exporter
")

(fs-mkdir "/home/user/scripts" #t)
(fs-write "/home/user/scripts/check-anomaly.sh"
"#!/bin/bash
# Quick script to check anomaly trend from watchdog logs
grep 'anomaly score' /var/log/syslog | tail -10
echo '---'
LATEST=$(grep 'anomaly score' /var/log/syslog | tail -1 | grep -oP '[0-9]+\\.[0-9]+')
echo \"Latest anomaly score: $LATEST\"
if (( $(echo \"$LATEST > 0.80\" | bc -l) )); then
    echo 'WARNING: anomaly score above 0.80 threshold'
fi
")
(fs-chmod "/home/user/scripts/check-anomaly.sh" 493)

;; ── /root (accessible but sparse) ─────────────────────────────────
(fs-write "/root/.bashrc"
"# root bashrc — minimal
export PS1='root@\\h:\\w# '
")

(fs-write "/root/.bash_history"
"/opt/nexus/watchdog.bin --status
systemctl restart nexus-monitor
cat /opt/nexus/.manifest
ssh -i /opt/nexus/.keys/master.key monitor.nexus
")

;; ── hidden depth: /opt/nexus/.manifest ────────────────────────────
(fs-write "/opt/nexus/.manifest"
"nexus-core:role=edge-node
nexus-core:sector=7G
nexus-core:tier=2
nexus-core:clearance=standard
nexus-core:monitor=monitor.nexus:4443
nexus-core:heartbeat_interval=10800
nexus-core:last_audit=2024-03-22T14:00:00Z
nexus-core:next_audit=pending
nexus-core:notes=anomaly pattern consistent with upstream propagation — escalated to tier-1 review
")

(fs-mkdir "/opt/nexus/.keys" #t)
(fs-write "/opt/nexus/.keys/master.key"
"-----BEGIN OPENSSH PRIVATE KEY-----
b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZW
QyNTUxOQAAACCsSdqy5gfBah70peXVlM8sdkdajaVu3pOGhZjd4UPipAAAAJhG7VxMRu1c
REDACTED-REDACTED-REDACTED-REDACTED-REDACTED-REDACTED-REDACTED-REDACTED
AAAAHnJvb3RAbmV4dXMtY29yZS5pbnRlcm5hbAECAwQF
-----END OPENSSH PRIVATE KEY-----
")
(fs-chmod "/opt/nexus/.keys/master.key" 384)
(fs-chmod "/opt/nexus/.keys" 448)

;; ── /dev (minimal device stubs) ───────────────────────────────────
(fs-write "/dev/null" "")
(fs-write "/dev/zero" "")
(fs-write "/dev/urandom" "")

;; ── processes ─────────────────────────────────────────────────────
(proc-add "init" 1
  (list (list "user" "root") (list "cpu" "0.0") (list "mem" "0.3")
        (list "vsz" "168832") (list "rss" "11264") (list "stat" "Ss")
        (list "start" "May28") (list "time" "0:03") (list "cmd" "/sbin/init")))

(proc-add "kthreadd" 2
  (list (list "user" "root") (list "cpu" "0.0") (list "mem" "0.0")
        (list "vsz" "0") (list "rss" "0") (list "tty" "?") (list "stat" "S")
        (list "start" "May28") (list "time" "0:00") (list "cmd" "[kthreadd]")))

(proc-add "systemd-journal" 412
  (list (list "user" "root") (list "cpu" "0.0") (list "mem" "0.5")
        (list "vsz" "42316") (list "rss" "18432") (list "tty" "?") (list "stat" "Ss")
        (list "start" "May28") (list "time" "0:12") (list "cmd" "/lib/systemd/systemd-journald")))

(proc-add "sshd" 856
  (list (list "user" "root") (list "cpu" "0.0") (list "mem" "0.2")
        (list "vsz" "15432") (list "rss" "5632") (list "tty" "?") (list "stat" "Ss")
        (list "start" "May28") (list "time" "0:00") (list "cmd" "sshd: /usr/sbin/sshd -D")))

(proc-add "cron" 923
  (list (list "user" "root") (list "cpu" "0.0") (list "mem" "0.1")
        (list "vsz" "8536") (list "rss" "3328") (list "tty" "?") (list "stat" "Ss")
        (list "start" "May28") (list "time" "0:01") (list "cmd" "/usr/sbin/cron -f")))

(proc-add "node_exporter" 1045
  (list (list "user" "root") (list "cpu" "0.1") (list "mem" "0.4")
        (list "vsz" "24576") (list "rss" "12288") (list "tty" "?") (list "stat" "Sl")
        (list "start" "May28") (list "time" "2:34") (list "cmd" "/usr/local/bin/node_exporter --web.listen-address=:9100")))

(proc-add "watchdog.bin" 1102
  (list (list "user" "root") (list "cpu" "0.0") (list "mem" "0.2")
        (list "vsz" "16384") (list "rss" "4096") (list "tty" "?") (list "stat" "Ss")
        (list "start" "May28") (list "time" "0:47") (list "cmd" "/opt/nexus/watchdog.bin --config /opt/nexus/watchdog.conf")))

(proc-add "bash" 5102
  (list (list "user" "user") (list "cpu" "0.0") (list "mem" "0.1")
        (list "vsz" "12344") (list "rss" "5120") (list "tty" "pts/0") (list "stat" "Ss")
        (list "start" "09:28") (list "time" "0:00") (list "cmd" "-bash")))
