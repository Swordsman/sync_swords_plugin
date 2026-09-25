;; Xylem Agent — self-modifying AI layer in Hy
(import os)
(import sys)
(import json)
(import hy :as hy-module)
(import pathlib [Path])
(import importlib)

(setv *version* "0.2.0")
(setv *agent-source* None)

(defn agent-status []
  (setv py-version (get (.split sys.version) 0))
  (print f"xylem agent v{*version*}")
  (print f"  pid:      {os.getpid}")
  (print f"  language: hy {hy-module.__version__}")
  (print f"  runtime:  python {py-version}"))

(defn read-self []
  (setv p (Path __file__))
  (setv *agent-source* (.read_text p))
  *agent-source*)

(defn rewrite-self [new-source]
  (.write-text (Path __file__) new-source)
  (.reload importlib (.import_module importlib __name__))
  (print "[xylem] agent rewrote itself"))

(defn eval-hy [code]
  (hy.eval (hy.read-many code)
           {'__name__ __name__ '__file__ __file__
            'os os 'sys sys}))

(print "[xylem] hy agent ready")
