"""Russian translations: {English source string: Russian text}.

``tests/unit/test_i18n.py`` fails when a ``tr("...")`` string in the code has no entry here.
"""

RU: dict[str, str] = {
    # --- engine errors -------------------------------------------------------------
    "Something went wrong. Details are in the log (Settings → Open log).":
        "Что-то пошло не так. Подробности — в журнале (Настройки → Открыть журнал).",
    "The model is not downloaded yet. Download it on the Models page.":
        "Модель ещё не скачана. Скачайте её на странице «Модели».",
    "The model could not be loaded. Its files may be damaged — "
    "delete it on the Models page and download it again.":
        "Не удалось загрузить модель. Возможно, файлы повреждены — удалите её на странице «Модели» "
        "и скачайте заново.",
    "The graphics card is not available to PyTorch. Check the diagnostics in "
    "Settings → This computer, or switch to the CPU-only mode.":
        "Видеокарта недоступна для PyTorch. Посмотрите диагностику в разделе «Настройки → Этот компьютер» "
        "или включите режим «Только процессор».",
    "This model cannot use a reference in this mode. "
    "Choose another reference mode or remove the reference.":
        "Эта модель не умеет работать с референсом в таком режиме. Выберите другой режим референса "
        "или уберите его.",
    "The reference image could not be opened. Use a PNG, JPG or WebP file.":
        "Не удалось открыть референс. Используйте файл PNG, JPG или WebP.",
    "This model needs a reference image as the first frame. "
    "Add one and try again.":
        "Этой модели нужен референс — первый кадр. Добавьте изображение и повторите.",
    "The style adapter could not be loaded. Check the internet connection — "
    "it is downloaded on first use.":
        "Не удалось загрузить адаптер стиля. Проверьте подключение к интернету — "
        "он скачивается при первом использовании.",
    "This model does not support LoRA. Remove the LoRA or pick another model.":
        "Эта модель не поддерживает LoRA. Уберите LoRA или выберите другую модель.",
    "The LoRA could not be attached. Make sure it was made for this model family.":
        "Не удалось подключить LoRA. Убедитесь, что она сделана для этого семейства моделей.",
    "There is nothing to read aloud. Enter some text.":
        "Нечего озвучивать. Введите текст.",
    "This model type is not supported yet.":
        "Модели такого типа пока не поддерживаются.",
    "The online voice component is not installed. Reinstall SnapReel "
    "or choose a local voice model.":
        "Компонент онлайн-голосов не установлен. Переустановите SnapReel или выберите локальную модель речи.",
    "No connection to the service. Check the internet connection and try again.":
        "Нет связи с сервисом. Проверьте подключение к интернету и повторите.",
    "The model is no longer in the list. Pick another model.":
        "Этой модели больше нет в списке. Выберите другую.",
    "This computer cannot run the model. The reason is shown under the model name.":
        "Этот компьютер не потянет модель. Причина указана под её названием.",
    "Not enough video memory. Lower the resolution or choose the "
    "“Low memory” mode in Settings.":
        "Не хватило видеопамяти. Уменьшите разрешение или выберите режим «Экономия памяти» в настройках.",
    # --- window and navigation -----------------------------------------------------
    "Image": "Изображение",
    "Video": "Видео",
    "Voice": "Озвучка",
    "Models": "Модели",
    "Gallery": "Галерея",
    "Settings": "Настройки",
    "This computer": "Этот компьютер",
    "Detecting hardware…": "Определяем железо…",
    "No graphics card — the processor will be used": "Видеокарты нет — будет использован процессор",
    "See Settings → This computer": "См. «Настройки → Этот компьютер»",
    "VRAM {used:.1f} / {total:.1f} GB": "VRAM {used:.1f} / {total:.1f} ГБ",
    "No model loaded": "Модель не загружена",
    "Unload the model and free memory": "Выгрузить модель и освободить память",
    "Queue: {count}": "В очереди: {count}",
    "Quit SnapReel": "Выход из SnapReel",
    "Generation or a download is in progress. Stop it and quit?":
        "Идёт генерация или загрузка. Прервать и выйти?",
    "SnapReel is already running.": "SnapReel уже запущен.",
    "Close": "Закрыть",
    # --- common widgets ------------------------------------------------------------
    "random": "случайный",
    "New random seed": "Новый случайный сид",
    "Use the last seed": "Повторить последний сид",
    "Use the last seed ({seed})": "Повторить последний сид ({seed})",
    "Width": "Ширина",
    "Height": "Высота",
    "Keep proportions": "Сохранять пропорции",
    "VRAM {need:.1f} / {have:.1f} GB": "VRAM {need:.1f} / {have:.1f} ГБ",
    "RAM {need:.1f} / {have:.1f} GB": "ОЗУ {need:.1f} / {have:.1f} ГБ",
    "The result will appear here": "Здесь появится результат",
    "Results of this session will line up here": "Здесь выстроятся результаты этого сеанса",
    "Reference image": "Референс",
    "Drop an image, click to choose or press Ctrl+V":
        "Перетащите изображение, нажмите, чтобы выбрать, или вставьте Ctrl+V",
    "Remove the reference": "Убрать референс",
    "Choose a reference image": "Выбор референса",
    # --- image page ----------------------------------------------------------------
    "Model": "Модель",
    "Prompt": "Промт",
    "Negative prompt": "Негативный промт",
    "What to avoid (optional)": "Чего избегать (необязательно)",
    "Structure": "Структура",
    "Style": "Стиль",
    "Edit": "Редактирование",
    "Keeps the composition of the reference; strength sets how much is redrawn.":
        "Сохраняет композицию референса; сила — насколько сильно он перерисовывается.",
    "Borrows the look of the reference; strength sets how closely it is followed.":
        "Перенимает стиль референса; сила — насколько точно ему следовать.",
    "The model edits the reference according to the prompt.": "Модель правит референс по промту.",
    "Strength": "Сила",
    "Format": "Формат",
    "Proportions": "Пропорции",
    "Exact size": "Точный размер",
    "Size": "Размер",
    "Native": "Родной",
    "Enlarging": "Увеличение",
    "Quality (Real-ESRGAN)": "Качественно (Real-ESRGAN)",
    "Fast": "Быстро",
    "File": "Файл",
    "{w} × {h} px": "{w} × {h} px",
    "{w} × {h} px — the model draws {gw} × {gh}, then it is enlarged":
        "{w} × {h} px — модель рисует {gw} × {gh}, затем изображение увеличивается",
    "Steps": "Шаги",
    "Prompt strength": "Сила промта",
    "How strictly the model follows the prompt.": "Насколько строго модель следует промту.",
    "Seed": "Сид",
    "Images": "Изображения",
    "Number of images": "Количество картинок",
    "Cancel (Esc)": "Отмена (Esc)",
    "Downloading": "Загрузка",
    "Download ({size:.1f} GB)": "Скачать ({size:.1f} ГБ)",
    "Add to queue": "В очередь",
    "Create": "Создать",
    "Waiting in the queue…": "Ожидание в очереди…",
    "Save as…": "Сохранить как…",
    "Save as": "Сохранить как",
    "Show in folder": "Показать в папке",
    "Copy to clipboard": "Копировать в буфер обмена",
    "Use as reference": "Использовать как референс",
    "Repeat with this seed": "Повторить с этим сидом",
    "Send to Video as the first frame": "Отправить в «Видео» как первый кадр",
    "seed": "сид",
    "Image copied": "Изображение скопировано",
    "The Video page is not available yet.": "Раздел «Видео» пока недоступен.",
    # --- redesign: window, image page, settings -----------------------------------
    "Local AI studio": "Локальная ИИ-студия",
    "In memory: {name}": "В памяти: {name}",
    "v{version} · by {author}": "v{version} · автор {author}",
    "Describe an idea — the model draws it right on your computer.":
        "Опишите идею — модель нарисует её прямо на вашем компьютере.",
    "A lighthouse on a cliff at dusk, warm light, film photo…":
        "Маяк на скале в сумерках, тёплый свет, плёночное фото…",
    "Tip: most models understand English best.": "Совет: большинство моделей лучше понимают английский.",
    "Reference (optional)": "Референс (необязательно)",
    "Advanced": "Дополнительно",
    "More steps — more detail, but slower.": "Больше шагов — больше деталей, но дольше.",
    "The same seed and settings repeat a picture.": "Тот же сид и настройки повторяют картинку.",
    "How many images to create": "Сколько картинок создать",
    "Create (Ctrl+Enter)": "Создать (Ctrl+Enter)",
    "What shall we create?": "Что создадим?",
    "Pick an idea to start from, or write your own on the left.":
        "Выберите идею для старта или напишите свою слева.",
    "Cozy reading nook by a rainy window": "Уютный уголок у дождливого окна",
    "Tiny island with a lighthouse, 3D": "Крошечный остров с маяком, 3D",
    "Portrait of an old sailor in oil": "Портрет старого моряка маслом",
    "Night street food stall in the rain": "Ночной уличный ларёк под дождём",
    "Changes are saved automatically.": "Изменения сохраняются автоматически.",
    "Appearance": "Внешний вид",
    "Language": "Язык",
    "Theme": "Тема",
    "Dark": "Тёмная",
    "Light": "Светлая",
    "Performance": "Производительность",
    "Memory mode": "Режим памяти",
    "Automatic": "Автоматически",
    "SnapReel picks the fastest mode that fits this computer.":
        "SnapReel сам выберет самый быстрый режим, который подходит этому компьютеру.",
    "Speed": "Скорость",
    "The whole model stays on the graphics card. Needs the most video memory.":
        "Вся модель находится на видеокарте. Нужно больше всего видеопамяти.",
    "Balanced": "Баланс",
    "Low memory": "Экономия памяти",
    "The model is streamed piece by piece. Slow, but runs on small graphics cards.":
        "Модель подгружается по частям. Медленно, но работает даже на слабых видеокартах.",
    "Processor only": "Только процессор",
    "No graphics card is used. Works everywhere, but very slowly.":
        "Видеокарта не используется. Работает везде, но очень медленно.",
    "Keep the model in memory between generations": "Держать модель в памяти между генерациями",
    "Faster repeats; turn off to free memory for other programs.":
        "Повторные генерации быстрее; выключите, чтобы освобождать память для других программ.",
    "Folders": "Папки",
    "Results": "Результаты",
    "Data and logs": "Данные и журнал",
    "Open": "Открыть",
    "Access token": "Токен доступа",
    "Needed only for models with restricted access. Stored on this computer in plain text in settings.json.":
        "Нужен только для моделей с ограниченным доступом. Хранится на этом компьютере открытым текстом в settings.json.",
    "About": "О программе",
    "A free studio for images, video and voice made by AI models that run on your own computer.":
        "Бесплатная студия для создания изображений, видео и озвучки ИИ-моделями, которые работают на вашем компьютере.",
    "Author of the implementation:": "Автор реализации:",
    "Author on GitHub": "Автор на GitHub",
    "Project page": "Страница проекта",
    "Open log": "Открыть журнал",
    "Model licenses are set by their authors; some allow only non-commercial use. The license is shown on each model's card.":
        "Лицензии моделей задают их авторы; некоторые разрешают только некоммерческое использование. Лицензия указана в карточке каждой модели.",
    # --- models page ---------------------------------------------------------------
    "Download ready-made models, find more on Hugging Face or add your own.":
        "Скачайте готовые модели, найдите новые на Hugging Face или добавьте свою.",
    "Models take {used} · {free} free": "Модели занимают {used} · свободно {free}",
    "Catalog": "Каталог",
    "Installed": "Установленные",
    "All": "Все",
    "Add your own": "Добавить свою",
    "Add your own model": "Своя модель",
    "Folder": "Папка",
    "Browse…": "Обзор…",
    "Check": "Проверить",
    "Checking…": "Проверяем…",
    "author/model or a link to its Hugging Face page": "автор/модель или ссылка на её страницу на Hugging Face",
    "Folder with a diffusers or transformers model": "Папка с моделью diffusers или transformers",
    "A .safetensors / .ckpt checkpoint or a Silero .pt file": "Чекпойнт .safetensors / .ckpt или файл Silero .pt",
    "Choose a model folder": "Выбор папки модели",
    "Choose a model file": "Выбор файла модели",
    "Recognized. Check the details and add it to your models.":
        "Модель распознана. Проверьте данные и добавьте её в свои модели.",
    "Add to my models": "Добавить в мои модели",
    "{name} added": "Модель «{name}» добавлена",
    "Search Hugging Face: flux, anime, portrait, tts…": "Поиск на Hugging Face: flux, anime, portrait, tts…",
    "Searching…": "Ищем…",
    "Nothing found. Try another word.": "Ничего не найдено. Попробуйте другое слово.",
    "{count} downloads · {likes} likes": "{count} загрузок · {likes} отметок",
    "In your list": "Уже в списке",
    "Check and add": "Проверить и добавить",
    "Nothing installed yet. Pick a model in the Catalog and press Download.":
        "Пока ничего не установлено. Выберите модель в каталоге и нажмите «Скачать».",
    "No models of this kind.": "Моделей такого вида нет.",
    "Restricted access: needs a Hugging Face token": "Ограниченный доступ: нужен токен Hugging Face",
    "Open the model page": "Открыть страницу модели",
    "Cancel the download": "Отменить загрузку",
    "Delete from disk": "Удалить с диска",
    "Remove from the list": "Убрать из списка",
    "no download": "без загрузки",
    "installed · {size}": "установлена · {size}",
    "{mb:.0f} MB": "{mb:.0f} МБ",
    "{gb:.1f} GB": "{gb:.1f} ГБ",
    "s": "с",
    "Downloading…": "Загрузка…",
    "Use": "Использовать",
    "Download": "Скачать",
    "Checking this computer…": "Проверяем этот компьютер…",
    "Delete model": "Удаление модели",
    "Remove “{name}” from the list? Its files on disk stay where they are.":
        "Убрать «{name}» из списка? Файлы на диске останутся на месте.",
    "Delete “{name}” ({size}) from disk? This cannot be undone; you can download it again.":
        "Удалить «{name}» ({size}) с диска? Отменить нельзя, но модель можно скачать заново.",
    "{name} is ready to use": "Модель «{name}» готова к работе",
    "This section is not available yet.": "Этот раздел пока недоступен.",
    # --- voice page ----------------------------------------------------------------
    "Type or paste text — a local model reads it aloud.":
        "Введите или вставьте текст — локальная модель прочитает его вслух.",
    "Hello! This is how your text will sound. Numbers like 2026 are read as words.":
        "Привет! Так прозвучит ваш текст. Числа вроде 2026 читаются словами.",
    "Text": "Текст",
    "{chars} characters · about {seconds:.0f} s of speech": "Символов: {chars} · около {seconds:.0f} с речи",
    "This voice works over the internet: your text is sent to Microsoft.":
        "Этот голос работает через интернет: ваш текст отправляется в Microsoft.",
    "Voice and sound": "Голос и звук",
    "Default voice": "Голос по умолчанию",
    "Speaker": "Голос",
    "Listen": "Прослушать",
    "Hear a short sample of this voice": "Прослушать короткий образец голоса",
    "Hello! This is how this voice sounds.": "Привет! Так звучит этот голос.",
    "Read aloud": "Озвучить",
    "Read aloud (Ctrl+Enter)": "Озвучить (Ctrl+Enter)",
    "Download ({size})": "Скачать ({size})",
    "Your voice-overs": "Ваши озвучки",
    "Your voice-overs will appear here. Write a few sentences on the left and press “Read aloud”.":
        "Здесь появятся ваши озвучки. Напишите пару предложений слева и нажмите «Озвучить».",
    "Play": "Воспроизвести",
    "Pause": "Пауза",
    # --- video page ----------------------------------------------------------------
    "Describe a scene and its motion — or bring it to life from a picture.":
        "Опишите сцену и движение — или оживите картинку.",
    "A paper boat floating on a calm lake at sunset, gentle ripples, slow camera pan…":
        "Бумажный кораблик на спокойном озере на закате, лёгкая рябь, медленная панорама…",
    "First frame (optional)": "Первый кадр (необязательно)",
    "Drop a picture to bring it to life, click to choose or press Ctrl+V":
        "Перетащите картинку, чтобы оживить её, нажмите, чтобы выбрать, или вставьте Ctrl+V",
    "This model needs a first frame: it animates a picture.":
        "Этой модели нужен первый кадр: она оживляет картинку.",
    "Duration": "Длительность",
    "Frame rate": "Частота кадров",
    "As the model": "Как у модели",
    "{frames} frames at {fps} fps · {seconds:.1f} s": "{frames} кадров при {fps} к/с · {seconds:.1f} с",
    "this is the model's limit": "это предел модели",
    "{w} × {h} px — the model films {gw} × {gh}, then frames are enlarged":
        "{w} × {h} px — модель снимает {gw} × {gh}, затем кадры увеличиваются",
    "Your video will play here. Describe a scene on the left and press “Create”.":
        "Здесь будет играть ваше видео. Опишите сцену слева и нажмите «Создать».",
    "Previous frame": "Предыдущий кадр",
    "Next frame": "Следующий кадр",
    "text encoder": "текстовый энкодер",
    "second text encoder": "второй текстовый энкодер",
    "main network": "основная сеть",
    "image decoder": "декодер изображения",
    # --- settings: computer, folders, formats, catalog, plugins ---------------------
    "Diagnostics": "Диагностика",
    "Processor: {name} · {cores} cores / {threads} threads": "Процессор: {name} · ядер {cores}, потоков {threads}",
    "Memory: {total:.1f} GB, {free:.1f} GB free": "Оперативная память: {total:.1f} ГБ, свободно {free:.1f} ГБ",
    "Graphics: {name}": "Видеокарта: {name}",
    "Graphics: none found": "Видеокарта: не найдена",
    "{gb:.1f} GB of video memory": "видеопамять {gb:.1f} ГБ",
    "driver {version}": "драйвер {version}",
    "with CUDA {version}": "с CUDA {version}",
    "without CUDA": "без CUDA",
    "PyTorch: not installed": "PyTorch: не установлен",
    "Free space for models: {size}": "Свободно для моделей: {size}",
    "No problems found. SnapReel uses this computer to the full.":
        "Проблем не найдено. SnapReel использует этот компьютер в полную силу.",
    "PyTorch is not installed, so nothing can be generated. Reinstall SnapReel.":
        "PyTorch не установлен, поэтому генерация невозможна. Переустановите SnapReel.",
    "PyTorch without NVIDIA graphics card support is installed: generation runs on the processor, tens of times slower.":
        "Установлен PyTorch без поддержки видеокарт NVIDIA: генерация идёт на процессоре, в десятки раз медленнее.",
    "{gpu} is not supported yet: SnapReel uses NVIDIA (CUDA) and Apple Silicon graphics. Models will run on the processor.":
        "{gpu} пока не поддерживается: SnapReel работает с видеокартами NVIDIA (CUDA) и Apple Silicon. Модели будут работать на процессоре.",
    "No graphics card found: models will run on the processor. Prefer the lightest models.":
        "Видеокарта не найдена: модели будут работать на процессоре. Выбирайте самые лёгкие.",
    "Less than 16 GB of RAM: heavy models may not fit.":
        "Оперативной памяти меньше 16 ГБ: тяжёлые модели могут не поместиться.",
    "Install the GPU version of PyTorch (about 3 GB)": "Установить GPU-версию PyTorch (около 3 ГБ)",
    "Download the SnapReel build for NVIDIA graphics cards from the project page.":
        "Скачайте сборку SnapReel для видеокарт NVIDIA со страницы проекта.",
    "PyTorch is already loaded in this session. Restart SnapReel and press the button before creating anything.":
        "PyTorch уже загружен в этом сеансе. Перезапустите SnapReel и нажмите кнопку до первой генерации.",
    "Downloading and installing… This takes several minutes.": "Скачиваем и устанавливаем… Это займёт несколько минут.",
    "Installed. Restart SnapReel to use the graphics card.":
        "Установлено. Перезапустите SnapReel, чтобы задействовать видеокарту.",
    "The GPU version of PyTorch is installed. Restart SnapReel.": "GPU-версия PyTorch установлена. Перезапустите SnapReel.",
    "Installation failed. Check the internet connection; details are in the log.":
        "Установка не удалась. Проверьте подключение к интернету; подробности — в журнале.",
    "Change…": "Изменить…",
    "Choose a folder": "Выбор папки",
    "Wait until downloads and generation finish, then change the folder.":
        "Дождитесь окончания загрузок и генерации, затем меняйте папку.",
    "SnapReel cannot write to this folder. Choose another one.": "SnapReel не может записывать в эту папку. Выберите другую.",
    "Models from the previous folder were not moved: {old}. Copy its contents here or download the models again.":
        "Модели из прежней папки не перенесены: {old}. Скопируйте её содержимое сюда или скачайте модели заново.",
    "Default file formats": "Форматы файлов по умолчанию",
    "PNG keeps the generation settings inside the file. MP4 plays everywhere; WebM is smaller; GIF suits messengers. WAV is lossless, MP3 is compact.":
        "PNG хранит настройки генерации внутри файла. MP4 открывается везде, WebM компактнее, GIF подходит для мессенджеров. WAV — без потерь, MP3 — компактный.",
    "Model catalog": "Каталог моделей",
    "Catalog address": "Адрес каталога",
    "A YAML list of models. Only Hugging Face repositories and trusted hosts are accepted from it; it never contains code.":
        "Список моделей в формате YAML. Из него принимаются только репозитории Hugging Face и доверенные сайты; кода в нём не бывает.",
    "Check for new models when SnapReel starts": "Проверять новые модели при запуске SnapReel",
    "Update now": "Обновить сейчас",
    "Tell me when a new version of SnapReel is released": "Сообщать о выходе новой версии SnapReel",
    "SnapReel {version} is available.": "Доступна новая версия SnapReel {version}.",
    "Open the page": "Открыть страницу",
    "Default address": "Адрес по умолчанию",
    "The address must start with https://": "Адрес должен начинаться с https://",
    "Catalog updated: {count} models.": "Каталог обновлён: моделей — {count}.",
    "Could not update the catalog: {reason}": "Не удалось обновить каталог: {reason}",
    "Plugins": "Плагины",
    "No plugins. A plugin adds a new engine for models that SnapReel cannot run yet.":
        "Плагинов нет. Плагин добавляет движок для моделей, которые SnapReel пока не умеет запускать.",
    "{name}: not loaded — {reason}": "{name}: не загружен — {reason}",
    "{name}: engines {engines}": "{name}: движки {engines}",
    "Plugins are Python code: put only files you trust in this folder. Changes apply after a restart.":
        "Плагины — это код на Python: кладите в эту папку только то, чему доверяете. Изменения применяются после перезапуска.",
    "Plugins folder": "Папка плагинов",
    # --- welcome screen --------------------------------------------------------------
    "Welcome": "Добро пожаловать",
    "Welcome screen": "Экран приветствия",
    "Welcome to SnapReel": "Добро пожаловать в SnapReel",
    "Create images, video and voice-overs with AI models right on your computer — free, and your ideas never leave it.":
        "Создавайте изображения, видео и озвучку ИИ-моделями прямо на своём компьютере — бесплатно, и ваши идеи никуда не уходят.",
    "From a prompt or a reference, in any size up to 4K and beyond.":
        "По описанию или референсу, в любом размере — до 4K и больше.",
    "Short clips from a description, or bring a picture to life.": "Короткие ролики по описанию — или оживите картинку.",
    "Natural speech from text, numbers are read as words.": "Естественная речь из текста, числа читаются словами.",
    "Your computer: {graphics} · {ram:.0f} GB of RAM": "Ваш компьютер: {graphics} · {ram:.0f} ГБ оперативной памяти",
    "{name}, {vram:.0f} GB of video memory": "{name}, видеопамять {vram:.0f} ГБ",
    "no graphics card": "видеокарты нет",
    "Generation will run on the processor; see Settings → This computer.":
        "Генерация будет идти на процессоре; подробности — в разделе «Настройки → Этот компьютер».",
    "Recommended to start": "Рекомендуем для начала",
    "SnapReel picked one model of each kind that suits this computer best. You can add more any time on the Models page.":
        "SnapReel подобрал по одной модели каждого вида, которые лучше всего подходят этому компьютеру. Другие можно добавить в любой момент в разделе «Модели».",
    "Choosing models for this computer…": "Подбираем модели для этого компьютера…",
    "installed": "установлена",
    "To download: {size} · {free} free on disk": "Будет скачано: {size} · свободно на диске {free}",
    "Download selected and start": "Скачать выбранное и начать",
    "Start creating": "Начать творить",
    "Skip for now": "Пропустить",
    "Downloads started. Progress is shown on the Create button and on the Models page.":
        "Загрузка началась. Прогресс виден на кнопке «Создать» и в разделе «Модели».",
    # --- gallery -------------------------------------------------------------------
    "{count} works": "Работ: {count}",
    "Nothing here yet": "Пока пусто",
    "Everything you create will be collected here.": "Здесь соберётся всё, что вы создадите.",
    "No works of this kind yet.": "Работ такого вида пока нет.",
    "Create the first image": "Создать первую картинку",
    "Repeat these settings": "Повторить с этими настройками",
    "Delete": "Удалить",
    "Delete this work and its file from disk? This cannot be undone.":
        "Удалить эту работу и её файл с диска? Отменить нельзя.",
    "{seconds} s": "{seconds} с",
    # --- progress stages -----------------------------------------------------------
    "Starting the engine…": "Запуск движка…",
    "Loading the model…": "Загрузка модели…",
    "Placing the model in memory…": "Размещение модели в памяти…",
    "Model ready": "Модель готова",
    "Generating…": "Генерация…",
    "Saving…": "Сохранение…",
    "Encoding the video…": "Кодирование видео…",
    "Enlarging the image…": "Увеличение изображения…",
    "Synthesizing speech…": "Синтез речи…",
    "Downloading additional files…": "Загрузка дополнительных файлов…",
    "Not enough memory — retrying in a leaner mode…":
        "Не хватило памяти — повтор в более экономном режиме…",
    # --- verdicts ------------------------------------------------------------------
    "Runs great": "Отлично подходит",
    "Runs well": "Подходит",
    "Slow": "Медленно",
    "Very slow": "Очень медленно",
    "Will not run": "Не запустится",
    # --- advisor notes -------------------------------------------------------------
    "Works over the internet: the text is sent to Microsoft.":
        "Работает через интернет: текст отправляется в Microsoft.",
    "PyTorch without graphics card support is installed. "
    "Install the GPU build in Settings → This computer.":
        "Установлен PyTorch без поддержки видеокарты. Установите GPU-сборку в разделе "
        "«Настройки → Этот компьютер».",
    "{gpu} is not supported yet; the model will run on the processor.":
        "{gpu} пока не поддерживается — модель будет работать на процессоре.",
    "Not enough disk space: {need:.1f} GB needed, {have:.1f} GB free.":
        "Не хватает места на диске: нужно {need:.1f} ГБ, свободно {have:.1f} ГБ.",
    "Runs on the processor — expect minutes instead of seconds.":
        "Работает на процессоре — счёт пойдёт на минуты, а не секунды.",
    "Needs about {need:.0f} GB of RAM, this computer has {have:.0f} GB.":
        "Нужно около {need:.0f} ГБ оперативной памяти, а в этом компьютере {have:.0f} ГБ.",
    "Needs about {need:.0f} GB of RAM out of {have:.0f} GB — "
    "Windows will use the page file, which is much slower.":
        "Нужно около {need:.0f} ГБ оперативной памяти из {have:.0f} ГБ — Windows задействует файл подкачки, "
        "это намного медленнее.",
    "Needs at least {need:.1f} GB of video memory, the graphics card has {have:.1f} GB.":
        "Нужно не меньше {need:.1f} ГБ видеопамяти, а у видеокарты {have:.1f} ГБ.",
    "Part of the model ({parts}) is streamed from RAM to fit the graphics card.":
        "Часть модели ({parts}) подгружается из оперативной памяти по ходу работы, чтобы уместиться в видеокарту.",
    "The model is streamed into video memory piece by piece: it fits, but slowly.":
        "Модель подгружается в видеопамять по частям: поместится, но будет медленно.",
    "Model parts take turns on the graphics card: a little slower, much less memory.":
        "Части модели по очереди занимают видеокарту: чуть медленнее, но памяти нужно намного меньше.",
    "The selected performance mode needs more video memory than available; "
    "generation may be very slow.":
        "Выбранный режим производительности требует больше видеопамяти, чем есть; "
        "генерация может идти очень медленно.",
    "The resolution is above what the model was trained on; details may repeat.":
        "Разрешение выше того, на котором обучалась модель; детали могут повторяться.",
    "Other programs occupy video memory ({free:.1f} GB free) — close them for full speed.":
        "Видеопамять занята другими программами (свободно {free:.1f} ГБ) — закройте их для полной скорости.",
    # --- hub / download errors -----------------------------------------------------
    "Access to this model is restricted. Accept its license on the Hugging Face page "
    "and enter your token in Settings.":
        "Доступ к модели ограничен. Примите её лицензию на странице Hugging Face и укажите токен в настройках.",
    "The model was not found. Check the name or the link.":
        "Модель не найдена. Проверьте название или ссылку.",
    "No connection to Hugging Face. Check the internet connection and try again.":
        "Нет связи с Hugging Face. Проверьте подключение к интернету и повторите.",
    "Enter the model as “author/name” or paste a link to its Hugging Face page.":
        "Укажите модель в виде «автор/название» или вставьте ссылку на её страницу на Hugging Face.",
    "This is an add-on (LoRA, adapter or ControlNet), not a standalone model.":
        "Это дополнение (LoRA, адаптер или ControlNet), а не самостоятельная модель.",
    "SnapReel cannot run this kind of model yet.":
        "SnapReel пока не умеет запускать модели такого типа.",
    "Not enough disk space for the download. Free some space or choose another "
    "models folder in Settings.":
        "Не хватает места на диске для загрузки. Освободите место или выберите другую папку моделей в настройках.",
}
