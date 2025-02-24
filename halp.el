;; Copyright 2006, 2008 Darius Bacon <darius@wry.me>
;; Distributed under the terms of the MIT X License, found at
;; http://www.opensource.org/licenses/mit-license.php

;; If for some reason you move the helper programs like pyhalp.py to a
;; different directory (not the one this file is loaded from) then set
;; this variable:
(defvar halp-helpers-directory nil
  "Directory where Halp helper scripts are installed.")


;; The rest of this file shouldn't need editing.

(require 'cl-lib)

(defun halp-add-all-hooks ()
  (halp-add-hook 'sh-mode-hook 'sh-mode-map "\M-i" 'halp-update-sh)
  ; Python mode might be called either py-mode or python-mode:
  (halp-add-hook 'py-mode-hook 'py-mode-map "\M-i" 'halp-update-python)
  (halp-add-hook 'python-mode-hook 'python-mode-map "\M-i" 'halp-update-python)
  (halp-add-hook 'haskell-mode-hook 'haskell-mode-map "\M-i"
                 'halp-update-haskell)
  (halp-add-hook 'literate-haskell-mode-hook 'literate-haskell-mode-map "\M-i"
                 'halp-update-literate-haskell)
  (halp-add-hook 'javascript-mode-hook 'javascript-mode-map "\M-i"
                 'halp-update-javascript)
  (halp-add-hook 'js-mode-hook 'js-mode-map "\M-i"
                 'halp-update-javascript)
;  (halp-add-hook 'emacs-lisp-mode-hook
;                 'emacs-lisp-mode-map "\M-i"
;                 'halp-update-emacs-lisp)
  )

(defun halp-add-hook (hook map-name key halp-update-function)
  (add-hook hook
            `(lambda ()
               (halp-buttonize-buffer)
               (define-key ,map-name ',key ',halp-update-function))))

(defun halp-update-sh ()
  (interactive)
  (halp-update-relative "sh-halp.sh" '()))

(defun halp-update-python ()
  (interactive)
  (halp-find-helpers-directory)
  (halp-py-update/diff (concat halp-helpers-directory "pyhalp.py") 
		       (list (buffer-name) (buffer-file-name))))

(defun halp-update-javascript ()
  (interactive)
  (halp-find-helpers-directory)
  (halp-py-update/diff (concat halp-helpers-directory "v8halp.py") '()))

(defun halp-update-haskell ()
  (interactive)
  (halp-py-update-relative "ghcihalp.py" '(".hs")))

(defun halp-update-literate-haskell ()
  (interactive)
  (halp-py-update-relative "ghcihalp.py" '(".lhs")))

(defun halp-py-update-relative (command args)
  (halp-find-helpers-directory)
  (halp-update "python" (cons (concat halp-helpers-directory command) args)))

(defun halp-update-relative (command args)
  (halp-find-helpers-directory)
  (halp-update (concat halp-helpers-directory command) args))

(defun halp-find-helpers-directory ()
  "Make halp-helpers-directory point to the directory it was
loaded from, if it's not yet initialized."
  (unless halp-helpers-directory
    (let ((filename (symbol-file 'halp-helpers-directory)))
      (when filename
        (setq halp-helpers-directory 
              (file-name-directory filename))))))


;; Running a helper command and applying its output

(defun halp-update (command args)
  "Update the current buffer using an external helper program."
  (interactive)
  (message "Halp starting...")
  (let ((output (halp-get-output-buffer)))
;;    (call-process-region (point-min) (point-max) "cat" t t)
    (let ((rc (apply 'call-process-region
                     (point-min) (point-max) command nil output nil 
                     args)))
      (cond ((zerop rc)                 ;success
             (halp-update-current-buffer output)
             (message "Halp starting... done"))
            ((numberp rc)
             (message "Halp starting... helper process failed"))
            (t (message rc))))))

(defun halp-py-update/diff (command args)
  (halp-update/diff "python" (cons command args)))

(defun halp-update/diff (command args)
  "Update the current buffer using an external helper program
that outputs a diff."
  (interactive)
  (message "Halp starting...")
  (let ((output (halp-get-output-buffer)))
    (let ((rc (apply 'call-process-region
                     (point-min) (point-max) command nil output nil 
                     args)))
      (cond ((zerop rc)                 ;success
             (let ((status (halp-update-current-buffer/diff output)))
               (message (concat "Halp starting... " status))))
            ((numberp rc)
             (message "Halp starting... helper process failed"))
            (t (message rc))))))

(defun halp-get-output-buffer ()
  "Return an empty buffer dedicated (hopefully) to halp's use."
  (let ((output (get-buffer-create "*halp-output*")))
    (save-current-buffer
      (set-buffer output)
      (erase-buffer))
    output))

(defun halp-update-current-buffer (output)
  "Update the current buffer using the output buffer."
  ;; Currently we just overwrite the original buffer with the output.
  ;; You could get the same effect, more easily, by setting
  ;; call-process-region's output buffer to t. (Commented out.)  But
  ;; we'll soon want to update things more intelligently.
  (let ((p (point)))
    (erase-buffer)
    (insert-buffer output)    ;XXX change to insert-buffer-substring ? the difference seems to be saving in the mark
    (goto-char p)))

(defun halp-update-current-buffer/diff (output)
  (save-excursion
    (halp-apply-diff (current-buffer) output)))


;;; Parsing and applying a diff

(defun halp-apply-diff (to-buffer from-buffer)
  (setq halp-argh '())
  (let ((status "ok"))
    (save-current-buffer
      (set-buffer from-buffer)
      (goto-char (point-min))
      (while (not (eobp))
        (cl-multiple-value-bind (lineno n-del start end) (halp-scan-chunk)
          (setq status "changed")
          (halp-dbg (list 'chunk lineno n-del start end))
          (set-buffer to-buffer)
          (goto-line lineno)
          (when (and (eobp) (/= (preceding-char) 10))
            ;; No newline at end of buffer; add it. Otherwise the
            ;; code below will delete the last line.
            (insert-char 10 1))
          (cl-multiple-value-bind (start1 end1) (halp-scan-lines n-del)
            (delete-region start1 end1)
            (halp-dbg (list 'deleted n-del start1 end1)))
          (insert-buffer-substring from-buffer start end)
          (set-buffer from-buffer))))
    status))

(defun halp-dbg (x)
  (setq halp-argh (cons x halp-argh)))

(defvar halp-argh nil)

(defun halp-scan-chunk ()
  (let* ((lineno (halp-scan-number))
         (n-del (halp-scan-number))
         (n-ins (halp-scan-number)))
    (forward-line)
    (cl-multiple-value-bind (start end) (halp-scan-lines n-ins)
      (cl-values lineno n-del start end))))

(defun halp-scan-lines (n)
  (let ((start (point)))
    (forward-line n)
    (cl-values start (point))))

(defun halp-scan-number ()
  (string-to-number (halp-scan-word)))

(defun halp-scan-word ()
  (let ((start (point)))
    (forward-word 1)
    (halp-from start)))

(defun halp-from (start)
  (buffer-substring start (point)))


;; Halp for elisp

(defun halp-update-emacs-lisp ()
  "Run all Emacs Lisp expressions in a buffer, and where there's
a ;;. comment after one, replace it with one holding the result."
  (interactive)
  (save-excursion
    (goto-char (point-min))
    (let (next-pos)
      (while (setq next-pos (scan-sexps (point) 1))
        (goto-char next-pos)
        (let ((result (eval (preceding-sexp))))
          (skip-chars-forward " \t\n")
          (when (looking-at ";;\\.")
            (delete-region (point) (save-excursion (forward-line 1) (point)))
            (insert ";;. ")
            (let ((standard-output (current-buffer)))
              (prin1 result))
            (insert "\n")))))))


;; Hyperlinks to other files

(defun halp-buttonize-buffer ()
  "Turn each <<foo>> in the current buffer into a button."
  (save-excursion
    (goto-char (point-min))
    (while (re-search-forward "<<[^<> ]+>>" nil t)
      (make-button (match-beginning 0)
                   (match-end 0)
                   :type 'halp-button))))

(define-button-type 'halp-button
  'follow-link t
  'action 'halp-button-action)

(defun halp-button-action (button)
  (find-file (buffer-substring (+ (button-start button) 2)
                               (- (button-end button) 2))))


;; Wrap-up

;;;###autoload
(defun halp ()
  (interactive)
  (halp-add-hook 'py-mode-hook 'py-mode-map "\M-i" 'halp-update-python))

(provide 'halp)
