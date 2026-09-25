(define (format-permissions perms is-dir)
  (let ((str (list (if is-dir "d" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 256) 2) 0)) "r" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 128) 2) 0)) "w" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 64) 2) 0)) "x" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 32) 2) 0)) "r" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 16) 2) 0)) "w" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 8) 2) 0)) "x" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 4) 2) 0)) "r" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 2) 2) 0)) "w" "-"))))
    (set! str (append str (list (if (not (eq? (modulo (/ perms 1) 2) 0)) "x" "-"))))
    (str-join str "")))

(define (format-ls-date mtime)
  (let ((month (format-time mtime "%b"))
        (day-str (format-time mtime "%d"))
        (time (format-time mtime "%H:%M")))
    (let ((day-num (string->number day-str)))
      (let ((day-out (if (lt? day-num 10)
                         (str-concat " " (number->string day-num))
                         (number->string day-num))))
        (str-concat month " " day-out " " time)))))

(register-command
  "pwd"
  (lambda (args stdin)
    (emit-line (state-get-cwd))
    0))

(register-command
  "cd"
  (lambda (args stdin)
    (let ((target #f))
      (if (eq? (length args) 0)
          (let ((home (env-get "HOME")))
            (if (eq? home "nil")
                (emit-error "cd: HOME not set")
                (set! target home)))
          (if (eq? (list-ref args 0) "-")
              (let ((old (env-get "OLDPWD")))
                (if (eq? old "nil")
                    (begin (emit-error "cd: OLDPWD not set") #f)
                    (begin
                      (set! target old)
                      (emit-line old)
                      #f)))
              (set! target (list-ref args 0))))
      (if (not target)
          0
          (let ((resolved (fs-resolve target)))
            (if (fs-is-dir resolved)
                (begin
                  (env-set "OLDPWD" (state-get-cwd))
                  (state-set-cwd resolved)
                  0)
                (if (fs-exists resolved)
                    (begin (emit-error (str-concat "cd: not a directory: " target)) 1)
                    (begin (emit-error (str-concat "cd: no such file or directory: " target)) 1))))))))

(register-command
  "echo"
  (lambda (args stdin)
    (let ((no-newline #f)
          (parts (list))
          (first #t))
      (for-each (lambda (arg)
                  (if (and first (eq? arg "-n"))
                      (set! no-newline #t)
                      (set! parts (append parts (list arg))))
                  (set! first #f))
                args)
      (let ((output (str-join parts " ")))
        (if no-newline
            (emit output)
            (emit-line output)))
      0)))

(register-command
  "cat"
  (lambda (args stdin)
    (if (eq? (length args) 0)
        (begin (emit stdin) 0)
        (let ((outputs (list)))
          (for-each (lambda (path)
                      (let ((content (fs-read path)))
                        (if (eq? content "nil")
                            (emit-error (str-concat "cat: " path ": No such file or directory"))
                            (set! outputs (append outputs (list content))))))
                    args)
          (emit (str-join outputs ""))
          0))))

(register-command
  "whoami"
  (lambda (args stdin)
    (emit-line (state-get "user"))
    0))

(register-command
  "hostname"
  (lambda (args stdin)
    (emit-line (state-get "hostname"))
    0))

(register-command
  "uname"
  (lambda (args stdin)
    (let ((all-flag #f))
      (for-each (lambda (arg)
                  (when (eq? arg "-a")
                    (set! all-flag #t)))
                args)
      (if all-flag
          (emit-line (str-concat "Linux " (state-get "hostname") " 5.15.0-generic #1 SMP x86_64 GNU/Linux"))
          (emit-line "Linux"))
      0)))

(register-command
  "id"
  (lambda (args stdin)
    (let ((user (state-get "user")))
      (emit-line (str-concat "uid=1000(" user ") gid=1000(" user ") groups=1000(" user ")"))
      0)))

(register-command
  "mkdir"
  (lambda (args stdin)
    (let ((parents #f)
          (dirs (list))
          (i 0)
          (len (length args)))
      (while (lt? i len)
        (let ((arg (list-ref args i)))
          (if (eq? arg "-p")
              (set! parents #t)
              (set! dirs (append dirs (list arg)))))
        (set! i (+ i 1)))
      (if (eq? (length dirs) 0)
          (emit-error "mkdir: missing operand")
          (for-each (lambda (d)
                      (let ((ok (fs-mkdir d parents)))
                        (when (not ok)
                          (emit-error (str-concat "mkdir: cannot create directory '" d "'")))))
                    dirs))
      0)))

(register-command
  "touch"
  (lambda (args stdin)
    (if (eq? (length args) 0)
        (emit-error "touch: missing file operand")
        (for-each (lambda (file)
                    (if (fs-exists file)
                        "nil"
                        (fs-write file "")))
                  args))
    0))

(register-command
  "cp"
  (lambda (args stdin)
    (if (lt? (length args) 2)
        (begin (emit-error "cp: missing file operand") 1)
        (let ((src (list-ref args 0))
              (dst (list-ref args 1)))
          (let ((content (fs-read src)))
            (if (eq? content "nil")
                (begin (emit-error (str-concat "cp: cannot stat '" src "': No such file or directory")) 1)
                (let ((ok (fs-write dst content)))
                  (if (not ok)
                      (begin (emit-error (str-concat "cp: cannot create '" dst "'")) 1)
                      0))))))))

(register-command
  "mv"
  (lambda (args stdin)
    (if (lt? (length args) 2)
        (begin (emit-error "mv: missing file operand") 1)
        (let ((src (list-ref args 0))
              (dst (list-ref args 1)))
          (let ((content (fs-read src)))
            (if (eq? content "nil")
                (begin (emit-error (str-concat "mv: cannot stat '" src "': No such file or directory")) 1)
                (begin
                  (fs-write dst content)
                  (fs-rm src #f)
                  0)))))))

(register-command
  "rm"
  (lambda (args stdin)
    (let ((recursive #f)
          (force-flag #f)
          (targets (list))
          (i 0)
          (len (length args)))
      (while (lt? i len)
        (let ((arg (list-ref args i)))
          (cond
            ((eq? arg "-r") (set! recursive #t))
            ((eq? arg "-rf") (begin (set! recursive #t) (set! force-flag #t)))
            ((eq? arg "-fr") (begin (set! recursive #t) (set! force-flag #t)))
            ((eq? arg "-f") (set! force-flag #t))
            (else (set! targets (append targets (list arg))))))
        (set! i (+ i 1)))
      (if (eq? (length targets) 0)
          (emit-error "rm: missing operand")
          (for-each (lambda (t)
                      (let ((ok (fs-rm t recursive)))
                        (when (and (not ok) (not force-flag))
                          (emit-error (str-concat "rm: cannot remove '" t "'")))))
                    targets))
      0)))

(register-command
  "clear"
  (lambda (args stdin)
    (emit "\033[2J\033[H")
    0))

(register-command
  "date"
  (lambda (args stdin)
    (emit-line (format-time (current-time) "%a %b %d %H:%M:%S %Z %Y"))
    0))

(register-command
  "env"
  (lambda (args stdin)
    (let ((vars (env-list)))
      (for-each (lambda (pair)
                  (emit-line (str-concat (list-ref pair 0) "=" (list-ref pair 1))))
                vars)
      0)))

(register-command
  "export"
  (lambda (args stdin)
    (if (eq? (length args) 0)
        (emit-error "export: missing argument")
        (for-each (lambda (arg)
                    (let ((parts (str-split arg "=")))
                      (if (eq? (length parts) 2)
                          (env-set (list-ref parts 0) (list-ref parts 1))
                          (emit-error (str-concat "export: invalid argument: " arg)))))
                  args))
    0))

(register-command
  "history"
  (lambda (args stdin)
    (let ((hist (history-list))
          (i 0))
      (for-each (lambda (entry)
                  (set! i (+ i 1))
                  (emit-line (str-concat (str-pad-right (number->string i) 5) "  " entry)))
                hist)
      0)))

;; --- Batch 2: ls, grep, head, tail, wc, ps, kill, ssh ---

(define (format-ls-long name path)
  (let* ((stat (fs-stat path))
         (perms (alist-ref "permissions" stat))
         (is-dir (alist-ref "is_dir" stat))
         (size (alist-ref "size" stat))
         (mtime (alist-ref "mtime" stat))
         (uid (alist-ref "uid" stat))
         (gid (alist-ref "gid" stat))
         (nlinks (alist-ref "nlinks" stat)))
    (if (eq? stat "nil")
        name
        (let* ((perm-str (format-permissions (if (number? perms) perms 420) (eq? is-dir #t)))
               (date-str (format-ls-date (if (number? mtime) mtime (current-time)))))
          (str-concat perm-str " "
                      (str-pad-right (number->string (if (number? nlinks) nlinks 1)) 3) " "
                      (str-pad-right (if (string? uid) uid "root") 8) " "
                      (str-pad-right (if (string? gid) gid "root") 8) " "
                      (str-pad-left (number->string (if (number? size) size 0)) 5) " "
                      date-str " "
                      name)))))

(register-command
  "ls"
  (lambda (args stdin)
    (let ((long-flag #f)
          (all-flag #f)
          (paths (list)))
      (let ((i 0)
            (len (length args)))
        (while (lt? i len)
          (let ((arg (list-ref args i)))
            (cond
              ((or (eq? arg "-la") (eq? arg "-al"))
               (begin (set! long-flag #t) (set! all-flag #t)))
              ((eq? arg "-l") (set! long-flag #t))
              ((eq? arg "-a") (set! all-flag #t))
              (else (set! paths (append paths (list arg))))))
          (set! i (+ i 1))))
      (when (eq? (length paths) 0)
        (set! paths (list ".")))
      (for-each (lambda (path)
                  (let ((entries (fs-list path)))
                    (if (eq? entries "nil")
                        (emit-error (str-concat "ls: cannot access '" path "': No such file or directory"))
                        (let ((filtered (list)))
                          (for-each (lambda (entry)
                                      (when (or all-flag (not (eq? (str-substr entry 0 1) ".")))
                                        (set! filtered (append filtered (list entry)))))
                                    entries)
                          (let ((sorted-entries (sort filtered)))
                            (if long-flag
                                (begin
                                  (emit-line (str-concat "total " (number->string (length sorted-entries))))
                                  (for-each (lambda (entry)
                                              (let ((full-path (if (eq? path ".")
                                                                   (str-concat (state-get-cwd) "/" entry)
                                                                   (str-concat path "/" entry))))
                                                (emit-line (format-ls-long entry full-path))))
                                            sorted-entries))
                                (emit-line (str-join sorted-entries "  "))))))))
                paths)
      0)))

(register-command
  "grep"
  (lambda (args stdin)
    (let ((ignore-case #f)
          (show-numbers #f)
          (recursive #f)
          (pattern #f)
          (files (list))
          (found #f))
      (let ((i 0)
            (len (length args)))
        (while (lt? i len)
          (let ((arg (list-ref args i)))
            (cond
              ((eq? arg "-i") (set! ignore-case #t))
              ((eq? arg "-n") (set! show-numbers #t))
              ((eq? arg "-r") (set! recursive #t))
              (else
               (if (not pattern)
                   (set! pattern arg)
                   (set! files (append files (list arg)))))))
          (set! i (+ i 1))))
      (if (not pattern)
          (begin (emit-error "grep: missing pattern") 2)
          (begin
            (when (eq? (length files) 0)
              (set! files (list "-")))
            (let ((multi (gt? (length files) 1)))
              (for-each (lambda (file)
                          (let ((content (if (eq? file "-")
                                             stdin
                                             (let ((c (fs-read file)))
                                               (if (eq? c "nil")
                                                   (begin
                                                     (emit-error (str-concat "grep: " file ": No such file or directory"))
                                                     #f)
                                                   c)))))
                            (when content
                              (let ((file-lines (str-lines content))
                                    (ln 0))
                                (for-each (lambda (line)
                                            (set! ln (+ ln 1))
                                            (let* ((test-line (if ignore-case (str-lower line) line))
                                                   (test-pat (if ignore-case (str-lower pattern) pattern)))
                                              (when (str-contains test-line test-pat)
                                                (set! found #t)
                                                (let ((out ""))
                                                  (when multi
                                                    (set! out (str-concat out file ":")))
                                                  (when show-numbers
                                                    (set! out (str-concat out (number->string ln) ":")))
                                                  (set! out (str-concat out line))
                                                  (emit-line out)))))
                                          file-lines)))))
                        files))
            (if found 0 1))))))

(register-command
  "head"
  (lambda (args stdin)
    (let ((n 10)
          (file "-"))
      (let ((i 0)
            (len (length args)))
        (while (lt? i len)
          (let ((arg (list-ref args i)))
            (cond
              ((eq? arg "-n")
               (set! i (+ i 1))
               (when (lt? i len)
                 (set! n (string->number (list-ref args i)))))
              (else (set! file arg))))
          (set! i (+ i 1))))
      (let ((content (if (eq? file "-")
                         stdin
                         (let ((c (fs-read file)))
                           (if (eq? c "nil")
                               (begin
                                 (emit-error (str-concat "head: cannot open '" file "' for reading"))
                                 "")
                               c)))))
        (let* ((file-lines (str-lines content))
               (total (length file-lines))
               (j 0))
          (while (and (lt? j n) (lt? j total))
            (emit-line (list-ref file-lines j))
            (set! j (+ j 1))))
        0))))

(register-command
  "tail"
  (lambda (args stdin)
    (let ((n 10)
          (file "-"))
      (let ((i 0)
            (len (length args)))
        (while (lt? i len)
          (let ((arg (list-ref args i)))
            (cond
              ((eq? arg "-n")
               (set! i (+ i 1))
               (when (lt? i len)
                 (set! n (string->number (list-ref args i)))))
              (else (set! file arg))))
          (set! i (+ i 1))))
      (let ((content (if (eq? file "-")
                         stdin
                         (let ((c (fs-read file)))
                           (if (eq? c "nil")
                               (begin
                                 (emit-error (str-concat "tail: cannot open '" file "' for reading"))
                                 "")
                               c)))))
        (let* ((file-lines (str-lines content))
               (total (length file-lines))
               (start (if (gt? n total) 0 (- total n)))
               (j start))
          (while (lt? j total)
            (emit-line (list-ref file-lines j))
            (set! j (+ j 1))))
        0))))

(register-command
  "wc"
  (lambda (args stdin)
    (let ((count-lines #f)
          (count-words #f)
          (count-chars #f)
          (files (list)))
      (let ((i 0)
            (len (length args)))
        (while (lt? i len)
          (let ((arg (list-ref args i)))
            (cond
              ((eq? arg "-l") (set! count-lines #t))
              ((eq? arg "-w") (set! count-words #t))
              ((eq? arg "-c") (set! count-chars #t))
              (else (set! files (append files (list arg))))))
          (set! i (+ i 1))))
      (when (and (not count-lines) (not count-words) (not count-chars))
        (set! count-lines #t)
        (set! count-words #t)
        (set! count-chars #t))
      (when (eq? (length files) 0)
        (set! files (list "-")))
      (for-each (lambda (file)
                  (let ((content (if (eq? file "-")
                                     stdin
                                     (let ((c (fs-read file)))
                                       (if (eq? c "nil")
                                           (begin
                                             (emit-error (str-concat "wc: " file ": No such file or directory"))
                                             "")
                                           c)))))
                    (let* ((l (length (str-lines content)))
                           (trimmed (str-trim content))
                           (w (if (eq? trimmed "") 0 (length (str-split trimmed " "))))
                           (c (str-length content))
                           (parts (list)))
                      (when count-lines
                        (set! parts (append parts (list (str-pad-left (number->string l) 8)))))
                      (when count-words
                        (set! parts (append parts (list (str-pad-left (number->string w) 8)))))
                      (when count-chars
                        (set! parts (append parts (list (str-pad-left (number->string c) 8)))))
                      (when (not (eq? file "-"))
                        (set! parts (append parts (list file))))
                      (emit-line (str-join parts " ")))))
                files)
      0)))

(register-command
  "ps"
  (lambda (args stdin)
    (emit-line "USER       PID %CPU %MEM    VSZ   RSS TTY      STAT START   TIME COMMAND")
    (let ((procs (proc-list)))
      (for-each (lambda (entry)
                  (let* ((pid (list-ref entry 0))
                         (info (list-ref entry 1))
                         (user (let ((u (alist-ref "user" info))) (if (eq? u "nil") "root" u)))
                         (cpu (let ((c (alist-ref "cpu" info))) (if (eq? c "nil") "0.0" c)))
                         (mem (let ((m (alist-ref "mem" info))) (if (eq? m "nil") "0.1" m)))
                         (vsz (let ((v (alist-ref "vsz" info))) (if (eq? v "nil") "4096" v)))
                         (rss (let ((r (alist-ref "rss" info))) (if (eq? r "nil") "1024" r)))
                         (tty (let ((t (alist-ref "tty" info))) (if (eq? t "nil") "?" t)))
                         (stat (let ((s (alist-ref "stat" info))) (if (eq? s "nil") "S" s)))
                         (start (let ((st (alist-ref "start" info))) (if (eq? st "nil") "00:00" st)))
                         (time-str (let ((ti (alist-ref "time" info))) (if (eq? ti "nil") "0:00" ti)))
                         (cmd (let ((c (alist-ref "cmd" info))) (if (eq? c "nil") "?" c))))
                    (emit-line (str-concat
                                 (str-pad-right user 8) " "
                                 (str-pad-right (number->string pid) 5) " "
                                 (str-pad-left cpu 4) " "
                                 (str-pad-left mem 4) " "
                                 (str-pad-left vsz 6) " "
                                 (str-pad-left rss 5) " "
                                 (str-pad-right tty 7) " "
                                 stat "   "
                                 start " "
                                 (str-pad-right time-str 8) " "
                                 cmd))))
                procs))
    0))

(register-command
  "kill"
  (lambda (args stdin)
    (let ((pids (list))
          (i 0)
          (len (length args)))
      (while (lt? i len)
        (let ((arg (list-ref args i)))
          (when (not (eq? (str-substr arg 0 1) "-"))
            (set! pids (append pids (list arg)))))
        (set! i (+ i 1)))
      (if (eq? (length pids) 0)
          (begin (emit-error "kill: usage: kill [-9] pid") 1)
          (let ((exit-code 0))
            (for-each (lambda (pid-str)
                        (let ((pid (string->number pid-str)))
                          (if (not (number? pid))
                              (begin
                                (emit-error (str-concat "kill: illegal pid: " pid-str))
                                (set! exit-code 1))
                              (let ((killed (proc-kill pid)))
                                (when (not killed)
                                  (emit-error (str-concat "kill: (" pid-str ") - No such process"))
                                  (set! exit-code 1))))))
                      pids)
            exit-code)))))

(register-command
  "ssh"
  (lambda (args stdin)
    (if (eq? (length args) 0)
        (begin (emit-error "ssh: missing hostname") 1)
        (let ((host (list-ref args 0)))
          (emit-error (str-concat "ssh: connect to host " host " port 22: Connection refused"))
          255))))

(define (find-match-name full-path name-pat)
  (let* ((parts (str-split full-path "/"))
         (basename (list-ref parts (- (length parts) 1))))
    (str-contains basename name-pat)))

(register-command
  "find"
  (lambda (args stdin)
    (let ((path ".")
          (name-pat #f))
      (let ((i 0)
            (len (length args)))
        (while (lt? i len)
          (let ((arg (list-ref args i)))
            (cond
              ((eq? arg "-name")
               (set! i (+ i 1))
               (when (lt? i len)
                 (set! name-pat (list-ref args i))))
              (else
               (when (not (str-starts-with arg "-"))
                 (set! path arg)))))
          (set! i (+ i 1))))
      (let ((walked (fs-walk path)))
        (for-each (lambda (entry)
                    (let ((dir-path (list-ref entry 0))
                          (dirs (list-ref entry 1))
                          (files (list-ref entry 2)))
                      (if name-pat
                          (begin
                            (when (find-match-name dir-path name-pat)
                              (emit-line dir-path))
                            (for-each (lambda (f)
                                        (let ((fp (str-concat dir-path "/" f)))
                                          (when (find-match-name fp name-pat)
                                            (emit-line fp))))
                                      files))
                          (begin
                            (emit-line dir-path)
                            (for-each (lambda (f)
                                        (emit-line (str-concat dir-path "/" f)))
                                      files)))))
                  walked))
      0)))

(register-command
  "which"
  (lambda (args stdin)
    (if (eq? (length args) 0)
        0
        (begin
          (for-each (lambda (cmd)
                      (let ((handler (lookup-command cmd)))
                        (if handler
                            (emit-line (str-concat "/usr/bin/" cmd))
                            (begin (emit-error (str-concat cmd " not found")) 1))))
                    args)
          0))))

(register-command
  "type"
  (lambda (args stdin)
    (for-each (lambda (cmd)
                (let ((handler (lookup-command cmd)))
                  (if handler
                      (emit-line (str-concat cmd " is /usr/bin/" cmd))
                      (emit-error (str-concat "bash: type: " cmd ": not found")))))
              args)
    0))
