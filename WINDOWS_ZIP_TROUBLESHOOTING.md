# Windows ZIP Troubleshooting ("File Not Found" from `dir *.zip`)

If Command Prompt shows **"File Not Found"** after `dir *.zip`, it usually means you are in the wrong folder.

## 1) Check where you are now

```bat
cd
```

## 2) Check common download folders

```bat
cd %USERPROFILE%\Downloads

dir *.zip
```

If still not found, try OneDrive-backed Downloads/Desktop:

```bat
cd %USERPROFILE%\OneDrive\Downloads

dir *.zip

cd %USERPROFILE%\OneDrive\Desktop

dir *.zip
```

## 3) Search your whole user profile for the export ZIP

```bat
dir %USERPROFILE%\DOWNLOAD_THIS_FROM_BROWSER_*.zip /s /b

dir %USERPROFILE%\Genesis_FULL_EXPORT_*.zip /s /b
```

This prints the full path(s) if found.

## 4) Copy the ZIP to C:\ or D:\ once you have the path

Replace `<FULL_PATH_FROM_SEARCH>` with the exact path returned above:

```bat
copy "<FULL_PATH_FROM_SEARCH>" C:\
copy "<FULL_PATH_FROM_SEARCH>" D:\
```

## Important

This Codex workspace is a separate Linux environment and cannot directly drop files into your Windows Downloads folder. You must download the ZIP from the browser UI first, then run the commands above on Windows.
