כאן שמים את fastboot.exe (מתוך platform-tools של Google), כדי שהתוכנה תשתמש בו
בנתיב יציב שבתוך הפרויקט — לא תלוי במיקום שלו במחשב.

מה להעתיק לתיקייה הזו (tools):
  - fastboot.exe
  - AdbWinApi.dll
  - AdbWinUsbApi.dll
(אפשר פשוט להעתיק את כל תוכן תיקיית platform-tools לכאן, או ליצור כאן תת-תיקייה
 בשם platform-tools ולשים בתוכה את הקבצים.)

התוכנה מחפשת את fastboot.exe לפי הסדר:
  1. בחירה ידנית בלשונית Fastboot (נשמרת)
  2. משתנה סביבה ASKATEROOV_FASTBOOT
  3. כאן:  tools\  /  tools\platform-tools\  /  bin\  /  platform-tools\  /  שורש הפרויקט
  4. ליד התיקייה הניידת של mtkclient
  5. ב-PATH של המערכת

חשוב: fastboot.exe זקוק ל-AdbWinApi.dll ו-AdbWinUsbApi.dll לידו, אחרת הוא לא ירוץ.
