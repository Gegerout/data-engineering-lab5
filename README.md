# Лабораторная 5. Менеджеры ресурсов Kubernetes

Вариант 9, программист, разработчик на мобильных платформах.

Репозиторий: https://github.com/Gegerout/data-engineering-lab5

Готовый отчет: [output/Лабораторная_работа_5_Kubernetes.pdf](output/Лабораторная_работа_5_Kubernetes.pdf).

## Результат

Kubernetes 1.32.2 поднят через kind 0.27.0 на macOS arm64 с Docker Desktop. Один узел управления и один рабочий узел. Docker имеет 12 CPU и 8 ГБ памяти. В конфигурации рабочего kubelet зарезервированы 10 CPU, поэтому для планирования Pod доступны 2 CPU. Это искусственное ограничение учебного стенда, не измерение загрузки процессора. Для другой машины нужно скорректировать kube-reserved, чтобы осталось 2 CPU.

Образ lab5-pairs:1 содержит расчет пар из третьей лабораторной. Условие варианта, нормализация навыков, GET Range и обработка границ строк перенесены без изменения. В новой программе считаются только пары, частичные суммы сохраняются в S3, затем объединяются отдельным Job.

При лимите 64Mi получен OOMKilled с кодом 137. Запуск с 512Mi дал пик cgroup 112902144 байт. Предел выбран по формуле ceil(peak * 1.25 / 32Mi) * 32Mi и равен 160Mi. Повторный запуск с этим пределом завершился успешно.

RustFS 1.0.0 перенесен внутрь кластера как Deployment с PVC 5Gi и Service rustfs. На томе четыре папки-диска, EC 2+2. Это схема хранилища из лабораторной 2; входной CSV взят из бакета hh-lake лабораторной 3. Объект перенесен через S3 API, SHA256 до и после совпал. PVC находится внутри Docker-узла kind. Он переживает пересоздание Pod, но удаление kind-кластера удалит локальные данные.

Indexed Job с completions=3 и parallelism=3 обрабатывает 26 сплитов по 32Mi. Сплит i берет Pod с индексом i % 3. Время работы трех Pod пересекается, это видно в logs/evidence/04_parallel.txt. Reduce запускается после успешного завершения всех трех частей. Для каждого индекса имя объекта одинаково при повторной попытке, поэтому попытка не добавляет вторую копию результата.

Одиночный и параллельный результаты совпали с ДЗ 3 по всем 12308 парам, сумма частот 48175. Топ-10 приведен в results/top10.csv и отчете. SHA256 итогового CSV 2fbb0cb56c472f162f2c184e7045ead2ab16727b84a9cab53a8ca359b0840f71.

Отдельно воспроизведены Pending с Insufficient cpu, Preempted для Pod с низким приоритетом и отказ Forbidden по ResourceQuota. Проверки CPU используют простые ожидающие процессы. Они резервируют CPU через requests, а не создают вычислительную нагрузку. Секреты не входят в образ или репозиторий.

## Повторение

Команды выполняются из корня этой папки. Нужны Docker, Python 3.12 и исходное RustFS из lab_03_mapreduce с объектом hh-lake/raw/it_vacancies_2024.csv на localhost:9010. Файл .env должен содержать RUSTFS_ACCESS_KEY и RUSTFS_SECRET_KEY этого хранилища. Скрипт setup.sh рассчитан на macOS arm64. На другой ОС установить kind и kubectl своей платформы в tmp/bin.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pyyaml
./scripts/setup.sh
.venv/bin/python scripts/experiments.py memory | tee logs/03_memory.txt
./scripts/kubectl.sh apply -f manifests/rustfs.yaml
./scripts/kubectl.sh -n lab5 rollout status deployment/rustfs --timeout=180s
./scripts/kubectl.sh -n lab5 port-forward service/rustfs 19010:9000
```

Последнюю команду оставить работающей в отдельном терминале. Затем:

```sh
.venv/bin/python scripts/experiments.py migrate | tee logs/04_migrate.txt
.venv/bin/python scripts/experiments.py parallel | tee logs/05_parallel.txt
.venv/bin/python scripts/experiments.py scheduling | tee logs/06_scheduling.txt
.venv/bin/python scripts/experiments.py quota | tee logs/07_quota.txt
.venv/bin/python scripts/verify.py
```

Сценарии предназначены для свежего кластера. Существующие Job с теми же именами не запускаются заново от kubectl apply. Сохраненные логи не перезаписывать без намерения повторить опыт. Для чтения результатов без запуска стенда достаточно `python3 scripts/verify.py`.

## Файлы

Dockerfile и requirements.txt задают образ. manifests содержит конфигурацию kind, Job, RustFS, PriorityClass, Pod для проверки CPU и ResourceQuota. scripts/experiments.py выполняет сценарии и проверяет их результаты; scripts/pairs.py выполняется в контейнере. input/lab3_pairs.csv является эталоном из третьей работы и должен попасть в репозиторий. Большой исходный CSV в репозиторий не включается.

logs содержит полные выводы и JSON состояния Kubernetes, logs/evidence содержит выводы команд и выдержки для снимков. scripts/evidence.py снимает их в Chromium без добавленных заголовков. Для него нужны playwright и установленный Chromium по пути /opt/homebrew/bin/chromium. Это снимки отображенных сохраненных выводов, их текст сверяется с исходником. Ожидаемый OOM и отказ квоты являются успешными результатами соответствующих экспериментов.

report содержит LaTeX, screenshots содержит изображения отчета, output содержит готовый PDF. materials содержит локальные материалы преподавателя, tmp содержит сборку и окружение kind; обе папки исключены из публикации. Диагностика настройки также сохранена в tmp/diagnostics.

Сборка PDF установленным Tectonic:

```sh
mkdir -p tmp/pdfs
tectonic --keep-logs -o tmp/pdfs report/main.tex
```

После проверки страниц копировать tmp/pdfs/main.pdf в output под именем итогового отчета.
