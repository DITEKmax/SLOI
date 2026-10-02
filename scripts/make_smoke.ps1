param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $speaker.GetInstalledVoices() | Where-Object {$_.Enabled}
$texts = @{
    'ru' = 'Это проверка локального распознавания речи. Сегодня мы изучаем программирование.'
    'en' = 'This is a local speech recognition test. Today we are discussing a university lecture.'
}
foreach($language in @('ru','en')) {
    $voice = $voices | Where-Object {$_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq $language} | Select-Object -First 1
    if($voice) {
        $speaker.SelectVoice($voice.VoiceInfo.Name)
        $speaker.SetOutputToWaveFile((Join-Path $OutputDirectory "$language.wav"))
        $speaker.Speak($texts[$language])
        $speaker.SetOutputToNull()
    }
}
$speaker.Dispose()
