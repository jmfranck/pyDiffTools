'from http://stackoverflow.com/questions/1858195/convert-xls-to-csv-on-command-line and https://msdn.microsoft.com/en-us/library/office/ff198017.aspx
if WScript.Arguments.Count < 2 Then
    WScript.Echo "Please specify the source and the destination files. Usage: xml2xls <xml source file> <xlsx destination file>"
    Wscript.Quit
End If

csv_format = 6
xlsx_format = 51
xml_spreadsheet = 46

if WScript.Arguments.Count = 4 Then
    input_format = WScript.Arguments.Item(2)
    output_format = WScript.Arguments.Item(3)
Else
    input_format = xml_spreadsheet
    output_format = xlsx_format
End If

Set objFSO = CreateObject("Scripting.FileSystemObject")

src_file = objFSO.GetAbsolutePathName(Wscript.Arguments.Item(0))
dest_file = objFSO.GetAbsolutePathName(WScript.Arguments.Item(1))

Dim oExcel
Set oExcel = CreateObject("Excel.Application")

Dim oBook
Set oBook = oExcel.Workbooks.Open(src_file)

oBook.SaveAs dest_file, output_format

oBook.Close False
oExcel.Quit
