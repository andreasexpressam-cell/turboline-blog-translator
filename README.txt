TurboLine Blog Translator v3

Διορθώσεις:
- Το fix casing είναι τώρα SRT-safe και δεν χαλάει index/timings.
- Πολύ πιο γρήγορη μετάφραση:
  - SRT σε μεγαλύτερα batches
  - απλό κείμενο ανά παραγράφους με translate_batch
- Για Ελληνικά γίνεται εσωτερικό humanize/polish.

Τρέξιμο:
1. Άνοιξε PowerShell μέσα στον φάκελο
2. pip install -r requirements.txt
3. py app.py
4. Άνοιξε browser: http://127.0.0.1:5000
