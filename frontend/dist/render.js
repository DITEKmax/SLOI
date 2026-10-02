var SloiRender = (function(Vue){const _Vue=Vue;return function render(_ctx, _cache) {
  with (_ctx) {
    const { createElementVNode: _createElementVNode, createTextVNode: _createTextVNode, withModifiers: _withModifiers, toDisplayString: _toDisplayString, normalizeClass: _normalizeClass, renderList: _renderList, Fragment: _Fragment, openBlock: _openBlock, createElementBlock: _createElementBlock, normalizeStyle: _normalizeStyle, createCommentVNode: _createCommentVNode, vModelSelect: _vModelSelect, withDirectives: _withDirectives, withKeys: _withKeys } = _Vue

    return (_openBlock(), _createElementBlock("div", {
      class: "workspace",
      "data-theme": theme,
      onDragover: _withModifiers(onDragOver, ["prevent"]),
      onDragleave: onDragLeave,
      onDrop: _withModifiers(onDrop, ["prevent"]),
      onKeydown: _withKeys($event => (appearance = false), ["esc"])
    }, [
      _createElementVNode("header", { class: "masthead" }, [_createElementVNode("a", {
        href: "#",
        class: "wordmark",
        "aria-label": "SLOI — локальная расшифровка",
        onClick: _withModifiers(() => {}, ["prevent"])
      }, [_createElementVNode("span", {
        class: "logo-symbol",
        "aria-hidden": "true"
      }, [
        _createElementVNode("i"),
        _createElementVNode("i"),
        _createElementVNode("i"),
        _createElementVNode("i")
      ]), _createTextVNode("SLOI"), _createElementVNode("span", { class: "wordmark-dot" }, "01")], 8, ["onClick"]), _createElementVNode("div", { class: "mast-caption" }, [_createElementVNode("span", null, "СИГНАЛ СТАНОВИТСЯ ТЕКСТОМ"), _createElementVNode("span", { class: "muted" }, "Локальная транскрипция / " + _toDisplayString(version), 1)]), _createElementVNode("div", { class: "mast-actions" }, [_createElementVNode("span", { class: "connection" }, [_createElementVNode("i", { class: _normalizeClass({online: connected}) }, null, 2), _createTextVNode(_toDisplayString(connected ? 'LOCAL / ONLINE' : 'ПЕРЕПОДКЛЮЧЕНИЕ'), 1)]), _createElementVNode("button", {
        class: "appearance-button",
        onClick: $event => (appearance = !appearance),
        "aria-expanded": appearance,
        "aria-controls": "appearance-panel"
      }, [_createElementVNode("span", {
        class: "theme-orbit",
        "aria-hidden": "true"
      }), _createTextVNode(_toDisplayString(theme.toUpperCase()), 1), _createElementVNode("span", { class: "plus-sign" }, _toDisplayString(appearance ? '−' : '+'), 1)], 8, ["onClick", "aria-expanded"])])]),
      appearance
        ? (_openBlock(), _createElementBlock("section", {
            key: 0,
            id: "appearance-panel",
            class: "appearance-panel",
            "aria-label": "Оформление"
          }, [
            _createElementVNode("div", { class: "panel-label" }, [_createTextVNode("ОФОРМЛЕНИЕ "), _createElementVNode("button", {
              onClick: $event => (appearance = false),
              "aria-label": "Закрыть оформление"
            }, "×", 8, ["onClick"])]),
            (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(themeList, (item, i) => {
              return (_openBlock(), _createElementBlock("button", {
                key: item.id,
                class: _normalizeClass(["theme-option", {selected: theme === item.id}]),
                onClick: $event => (chooseTheme(item.id))
              }, [_createElementVNode("span", { class: "theme-number" }, "0" + _toDisplayString(i + 1), 1), _createElementVNode("span", null, [_createTextVNode(_toDisplayString(item.name), 1), _createElementVNode("small", null, _toDisplayString(item.description), 1)]), _createElementVNode("span", { class: "theme-check" }, _toDisplayString(theme === item.id ? '●' : '○'), 1)], 10, ["onClick"]))
            }), 128)),
            _createElementVNode("div", { class: "accent-title" }, [_createTextVNode("АКЦЕНТ "), _createElementVNode("span", null, _toDisplayString(accent.toUpperCase()), 1)]),
            _createElementVNode("div", { class: "swatches" }, [(_openBlock(true), _createElementBlock(_Fragment, null, _renderList(presets, (color) => {
              return (_openBlock(), _createElementBlock("button", {
                key: color,
                style: _normalizeStyle({'--swatch':color}),
                class: _normalizeClass({selected:accent===color}),
                onClick: $event => (setAccent(color)),
                "aria-label": 'Акцент '+color
              }, null, 14, ["onClick", "aria-label"]))
            }), 128)), _createElementVNode("label", {
              class: "custom-color",
              title: "Свой цвет"
            }, [_createTextVNode("＋"), _createElementVNode("input", {
              type: "color",
              value: accent,
              onInput: $event => (setAccent($event.target.value)),
              "aria-label": "Свой акцентный цвет"
            }, null, 40, ["value", "onInput"])])]),
            _createElementVNode("p", null, "Цвет, шрифт, геометрия и движение. Одна рабочая среда — три характера.")
          ]))
        : _createCommentVNode("", true),
      error
        ? (_openBlock(), _createElementBlock("div", {
            key: 1,
            role: "alert",
            class: "notice error-notice"
          }, [_createElementVNode("span", null, _toDisplayString(error), 1), _createElementVNode("button", {
            onClick: $event => (error = ''),
            "aria-label": "Закрыть сообщение"
          }, "×", 8, ["onClick"])]))
        : _createCommentVNode("", true),
      info
        ? (_openBlock(), _createElementBlock("div", {
            key: 2,
            role: "status",
            class: "notice"
          }, [_createElementVNode("span", null, _toDisplayString(info), 1), _createElementVNode("button", {
            onClick: $event => (info = ''),
            "aria-label": "Закрыть сообщение"
          }, "×", 8, ["onClick"])]))
        : _createCommentVNode("", true),
      (!anyInstalled && connected)
        ? (_openBlock(), _createElementBlock("div", {
            key: 3,
            class: "setup-notice"
          }, [_createTextVNode("Веса и GPU-окружения ещё не установлены. Закройте приложение и запустите "), _createElementVNode("strong", null, "install.bat"), _createTextVNode(". Значения GPU не подменяются тестовыми.")]))
        : _createCommentVNode("", true),
      _createElementVNode("main", null, [_createElementVNode("section", {
        class: "instrument",
        "aria-label": "Текущая обработка"
      }, [_createElementVNode("div", { class: "hero" }, [
        _createElementVNode("div", { class: "hero-top" }, [_createElementVNode("div", { class: "eyebrow" }, [_createElementVNode("span", { class: "section-index" }, "01 /"), _createTextVNode(" " + _toDisplayString(active ? 'АКТИВНЫЙ СИГНАЛ' : selected ? 'ЗАПИСЬ' : 'ПОЛЕ СИГНАЛА'), 1)]), _createElementVNode("span", { class: "stage-label" }, [_createElementVNode("i", { class: _normalizeClass({pulse:!!active}) }, null, 2), _createTextVNode(_toDisplayString(busyNative ? 'ОКНО WINDOWS ОТКРЫТО' : statusText(selected?.status)), 1)])]),
        selected
          ? (_openBlock(), _createElementBlock("div", {
              key: 0,
              class: "source-info"
            }, [_createElementVNode("h1", { title: selected.name }, _toDisplayString(selected.name), 9, ["title"]), _createElementVNode("div", { class: "source-tags" }, [
              _createElementVNode("span", null, _toDisplayString(modelName(selected.model)), 1),
              _createElementVNode("span", null, _toDisplayString(languageText(selected.language)), 1),
              _createElementVNode("span", null, _toDisplayString(time(selected.duration)), 1),
              _createElementVNode("span", null, _toDisplayString(selected.attempt > 1 ? 'ПОПЫТКА '+selected.attempt : 'ИСХОДНИК НЕ ИЗМЕНЯЕТСЯ'), 1)
            ])]))
          : (_openBlock(), _createElementBlock("div", {
              key: 1,
              class: "source-info"
            }, [_createElementVNode("h1", null, [_createTextVNode("Из речи."), _createElementVNode("br"), _createElementVNode("em", null, "В текст.")]), _createElementVNode("div", { class: "source-tags" }, [_createElementVNode("span", null, "АУДИО И ВИДЕО"), _createElementVNode("span", null, "НА ВАШЕМ КОМПЬЮТЕРЕ")])])),
        _createElementVNode("canvas", {
          ref: "fieldCanvas",
          class: "signal-canvas",
          "aria-hidden": "true"
        }, null, 512),
        _createElementVNode("div", { class: "field-caption" }, [_createElementVNode("span", null, _toDisplayString(theme === 'paper' ? 'РЕЧЬ / СТРУКТУРА / ТЕКСТ' : 'SIGNAL → STRUCTURE → TEXT'), 1), _createElementVNode("span", null, _toDisplayString(active ? 'ПО ДАННЫМ ЗАДАЧИ' : 'ВИЗУАЛЬНОЕ ПОЛЕ'), 1)]),
        (selected && selected.status !== 'WAITING')
          ? (_openBlock(), _createElementBlock("div", {
              key: 2,
              class: "progress-stage"
            }, [_createElementVNode("div", { class: _normalizeClass(["progress-number", {indeterminate: percentage === null}]) }, [_createElementVNode("span", null, _toDisplayString(percentage === null ? '—' : percentage.toFixed(1)), 1), (percentage !== null)
              ? (_openBlock(), _createElementBlock("sup", { key: 0 }, "%"))
              : _createCommentVNode("", true)], 2), _createElementVNode("div", { class: "progress-copy" }, [_createElementVNode("span", null, _toDisplayString(progressCaption), 1), _createElementVNode("strong", null, [_createTextVNode(_toDisplayString(time(selected.processed_seconds)), 1), _createElementVNode("span", { class: "muted" }, " / " + _toDisplayString(time(selected.planned_seconds)), 1)]), _createElementVNode("small", null, _toDisplayString(selected.status === 'ANALYSING' ? 'Прочитано '+time(selected.analysis_seconds) : 'Подтверждённые участки аудио'), 1)])]))
          : (_openBlock(), _createElementBlock("div", {
              key: 3,
              class: "empty-action"
            }, [_createElementVNode("button", {
              class: "primary-button",
              onClick: $event => (nativeFiles('picker')),
              disabled: busyNative || !connected
            }, [_createElementVNode("span", null, "Добавить записи"), _createElementVNode("span", { class: "button-arrow" }, "↗")], 8, ["onClick", "disabled"]), _createElementVNode("span", null, [_createTextVNode("Без загрузки медиа на сервер."), _createElementVNode("br"), _createTextVNode("Оригиналы остаются на своих местах.")])])),
        _createElementVNode("div", {
          class: "progress-track",
          role: "progressbar",
          "aria-label": "Распознано аудио",
          "aria-valuenow": percentage === null ? undefined : percentage,
          "aria-valuemin": "0",
          "aria-valuemax": "100",
          "aria-valuetext": percentage === null ? statusText(selected?.status) : percentage.toFixed(1)+'%'
        }, [_createElementVNode("div", {
          class: "progress-fill",
          style: _normalizeStyle({width:(percentage ?? 0)+'%'})
        }, null, 4), (selected?.speech_map?.length)
          ? (_openBlock(), _createElementBlock("div", {
              key: 0,
              class: "speech-stripes"
            }, [(_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selected.speech_map, (level, i) => {
              return (_openBlock(), _createElementBlock("i", {
                key: i,
                style: _normalizeStyle({opacity:0.12+level*0.72})
              }, null, 4))
            }), 128))]))
          : _createCommentVNode("", true), (percentage !== null)
          ? (_openBlock(), _createElementBlock("span", {
              key: 1,
              class: "progress-cursor",
              style: _normalizeStyle({left:Math.min(99.8,percentage)+'%'})
            }, null, 4))
          : _createCommentVNode("", true)], 8, ["aria-valuenow", "aria-valuetext"]),
        _createElementVNode("div", { class: "timeline-meta" }, [_createElementVNode("span", null, _toDisplayString(selected ? time(selected.elapsed_seconds)+' ПРОШЛО' : 'WAV · MP3 · M4A · FLAC · MP4 · MOV · MKV'), 1), active
          ? (_openBlock(), _createElementBlock("span", { key: 0 }, _toDisplayString(selected?.eta_seconds != null ? '≈ '+time(selected.eta_seconds)+' ОСТАЛОСЬ' : 'ОЦЕНКА ВРЕМЕНИ…'), 1))
          : (_openBlock(), _createElementBlock("span", { key: 1 }, _toDisplayString(completed.length ? completed.length+' ГОТОВО К СКАЧИВАНИЮ' : 'ОРИГИНАЛ → ТОЛЬКО ЧТЕНИЕ'), 1))]),
        (selected?.error)
          ? (_openBlock(), _createElementBlock("div", {
              key: 4,
              class: "job-error",
              role: "alert"
            }, [_createElementVNode("strong", null, _toDisplayString(selected.error.code), 1), _createElementVNode("p", null, _toDisplayString(selected.error.message), 1)]))
          : _createCommentVNode("", true),
        (selected?.warnings?.length)
          ? (_openBlock(), _createElementBlock("div", {
              key: 5,
              class: "job-warning"
            }, [_createElementVNode("details", null, [_createElementVNode("summary", null, "Примечания к обработке · " + _toDisplayString(selected.warnings.length), 1), (_openBlock(true), _createElementBlock(_Fragment, null, _renderList(selected.warnings, (warning) => {
              return (_openBlock(), _createElementBlock("p", { key: warning }, _toDisplayString(warning), 1))
            }), 128))])]))
          : _createCommentVNode("", true)
      ]), _createElementVNode("aside", {
        class: "telemetry",
        "aria-label": "Ресурсы компьютера"
      }, [
        _createElementVNode("div", { class: "telemetry-head" }, [_createElementVNode("span", { class: "eyebrow" }, [_createElementVNode("span", { class: "section-index" }, "02 /"), _createTextVNode(" СИСТЕМА")]), _createElementVNode("span", {
          class: "live-squares",
          "aria-hidden": "true"
        }, "▪ ▪ ▪")]),
        _createElementVNode("p", { class: "device-name" }, _toDisplayString(telemetry.gpu_name || 'NVIDIA GPU не обнаружена'), 1),
        _createElementVNode("div", { class: "metric metric-gpu" }, [_createElementVNode("div", { class: "metric-label" }, [_createElementVNode("span", null, "GPU"), _createElementVNode("span", null, "ЗАГРУЗКА")]), _createElementVNode("div", { class: "metric-value" }, [_createTextVNode(_toDisplayString(metric(telemetry.gpu_utilization_pct,0)), 1), _createElementVNode("span", null, "%")]), (_openBlock(), _createElementBlock("svg", {
          class: "sparkline",
          viewBox: "0 0 300 35",
          preserveAspectRatio: "none",
          "aria-hidden": "true"
        }, [_createElementVNode("path", {
          class: "spark-baseline",
          d: "M0 34H300"
        }), _createElementVNode("path", { d: spark('gpu_utilization_pct',100) }, null, 8, ["d"])]))]),
        _createElementVNode("div", { class: "metric metric-vram" }, [_createElementVNode("div", { class: "metric-label" }, [_createElementVNode("span", null, "VRAM"), _createElementVNode("span", null, "ВИДЕОПАМЯТЬ")]), _createElementVNode("div", { class: "vram-value" }, [_createTextVNode(_toDisplayString(gb(telemetry.gpu_memory_used_mb)), 1), _createElementVNode("span", null, [_createTextVNode(" / " + _toDisplayString(gb(telemetry.gpu_memory_total_mb)) + " ", 1), _createElementVNode("small", null, "GB")])]), _createElementVNode("div", { class: "resource-track" }, [_createElementVNode("span", { style: _normalizeStyle({width:ratio(telemetry.gpu_memory_used_mb,telemetry.gpu_memory_total_mb)+'%'}) }, null, 4)])]),
        _createElementVNode("div", { class: "minor-metrics" }, [_createElementVNode("div", { class: "metric" }, [_createElementVNode("div", { class: "metric-label" }, [_createElementVNode("span", null, "CPU")]), _createElementVNode("div", { class: "minor-value" }, [_createTextVNode(_toDisplayString(metric(telemetry.cpu_utilization_pct,0)), 1), _createElementVNode("small", null, "%")]), (_openBlock(), _createElementBlock("svg", {
          viewBox: "0 0 140 22",
          preserveAspectRatio: "none",
          "aria-hidden": "true"
        }, [_createElementVNode("path", { d: spark('cpu_utilization_pct',100,140,22) }, null, 8, ["d"])]))]), _createElementVNode("div", { class: "metric" }, [_createElementVNode("div", { class: "metric-label" }, [_createElementVNode("span", null, "RAM")]), _createElementVNode("div", { class: "minor-value" }, [_createTextVNode(_toDisplayString(gb(telemetry.system_ram_used_mb,1)), 1), _createElementVNode("small", null, "GB")]), _createElementVNode("div", { class: "minor-foot" }, "из " + _toDisplayString(gb(telemetry.system_ram_total_mb,1)) + " GB", 1)])]),
        _createElementVNode("div", { class: "thermal-row" }, [_createElementVNode("span", null, [_createTextVNode("ТЕМПЕРАТУРА "), _createElementVNode("strong", null, _toDisplayString(metric(telemetry.gpu_temperature_c,0)) + "°", 1)]), _createElementVNode("span", null, [_createTextVNode("ПИТАНИЕ "), _createElementVNode("strong", null, [_createTextVNode(_toDisplayString(metric(telemetry.gpu_power_w,0)) + " ", 1), _createElementVNode("small", null, "W")])])]),
        _createElementVNode("div", { class: "speed-metric" }, [_createElementVNode("div", { class: "eyebrow" }, "СКОРОСТЬ ОБРАБОТКИ"), _createElementVNode("div", null, [_createTextVNode(_toDisplayString(metric(selected?.speed_x,1)), 1), _createElementVNode("sup", null, "×")]), _createElementVNode("p", null, [_createTextVNode("от длительности исходника"), _createElementVNode("em", null, "ВКЛЮЧАЯ ПОДГОТОВКУ")])])
      ])]), _createElementVNode("section", {
        class: "queue-section",
        "aria-label": "Очередь файлов"
      }, [
        _createElementVNode("div", { class: "queue-header" }, [_createElementVNode("h2", null, [_createElementVNode("span", { class: "section-index" }, "03 /"), _createTextVNode(" Очередь"), _createElementVNode("span", { class: "queue-counter" }, _toDisplayString(String(allJobs.length).padStart(2,'0')), 1)]), _createElementVNode("div", { class: "queue-summary" }, [_createTextVNode(_toDisplayString(time(totalDuration)) + " АУДИО ", 1), _createElementVNode("span", null, "/"), _createTextVNode(" " + _toDisplayString(completed.length) + " ГОТОВО", 1)]), (completed.length)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "text-button",
              onClick: downloadAll
            }, [_createTextVNode("Скачать всё "), _createElementVNode("span", null, "↓")], 8, ["onClick"]))
          : _createCommentVNode("", true)]),
        (!allJobs.length)
          ? (_openBlock(), _createElementBlock("div", {
              key: 0,
              class: "queue-empty"
            }, [_createElementVNode("div", null, [_createElementVNode("span", { class: "cross-mark" }, "＋"), _createElementVNode("p", null, [_createTextVNode("Следующая запись начинается здесь."), _createElementVNode("small", null, "Добавьте несколько файлов, выберите модель и язык.")])]), _createElementVNode("button", {
              class: "text-button",
              onClick: $event => (nativeFiles('drop')),
              disabled: busyNative || !connected
            }, "Открыть Windows drop-зону ↗", 8, ["onClick", "disabled"])]))
          : (_openBlock(), _createElementBlock("div", {
              key: 1,
              class: "queue-list"
            }, [(_openBlock(true), _createElementBlock(_Fragment, null, _renderList(allJobs, (job, index) => {
              return (_openBlock(), _createElementBlock("article", {
                key: job.id,
                class: _normalizeClass(["queue-row", {active:job.id===queue.active_id,done:job.status==='COMPLETE',failed:['FAILED','INTERRUPTED','SOURCE_MISSING'].includes(job.status)}]),
                draggable: job.status==='WAITING',
                onDragstart: $event => (rowDragStart($event,job)),
                onDragover: _withModifiers(() => {}, ["prevent","stop"]),
                onDrop: _withModifiers($event => (rowDrop(job)), ["prevent","stop"]),
                onDragend: $event => (dragJob='')
              }, [
                _createElementVNode("div", { class: "queue-index" }, [_createElementVNode("span", null, _toDisplayString(String(index+1).padStart(2,'0')), 1), (job.id===queue.active_id)
                  ? (_openBlock(), _createElementBlock("i", {
                      key: 0,
                      class: "equalizer",
                      "aria-hidden": "true"
                    }, [_createElementVNode("b"), _createElementVNode("b"), _createElementVNode("b")]))
                  : (job.status==='COMPLETE')
                    ? (_openBlock(), _createElementBlock("span", {
                        key: 1,
                        class: "complete-tick"
                      }, "↗"))
                    : (_openBlock(), _createElementBlock("span", {
                        key: 2,
                        class: "drag-mark",
                        "aria-hidden": "true"
                      }, "⠿"))]),
                _createElementVNode("div", { class: "queue-file" }, [_createElementVNode("button", {
                  class: "job-name-button",
                  title: job.name,
                  onClick: $event => (selectJob(job))
                }, _toDisplayString(job.name), 9, ["title", "onClick"]), _createElementVNode("small", null, [
                  _createTextVNode(_toDisplayString(time(job.duration)) + " ", 1),
                  _createElementVNode("span", null, "·"),
                  _createTextVNode(" " + _toDisplayString(job.media_type === 'video' ? 'ВИДЕО' : 'АУДИО') + " ", 1),
                  _createElementVNode("span", null, "·"),
                  _createTextVNode(" " + _toDisplayString(size(job.size)), 1)
                ])]),
                _createElementVNode("div", { class: "queue-choice" }, [_createElementVNode("select", {
                  value: job.model,
                  onChange: $event => (changeModel(job,$event.target.value)),
                  disabled: job.status!=='WAITING',
                  "aria-label": 'Модель для '+job.name
                }, [(_openBlock(true), _createElementBlock(_Fragment, null, _renderList(models, (model) => {
                  return (_openBlock(), _createElementBlock("option", {
                    key: model.id,
                    value: model.id,
                    disabled: !model.installed
                  }, _toDisplayString(model.name) + _toDisplayString(!model.installed ? ' · нет весов' : ''), 9, ["value", "disabled"]))
                }), 128))], 40, ["value", "onChange", "disabled", "aria-label"]), _createElementVNode("select", {
                  value: job.language,
                  onChange: $event => (changeLanguage(job,$event.target.value)),
                  disabled: job.status!=='WAITING',
                  "aria-label": 'Основной язык '+job.name
                }, [_createElementVNode("option", { value: "auto" }, "AUTO"), _createElementVNode("option", { value: "ru" }, "RU +"), _createElementVNode("option", {
                  value: "en",
                  disabled: job.model==='gigaam'
                }, "EN +", 8, ["disabled"])], 40, ["value", "onChange", "disabled", "aria-label"])]),
                _createElementVNode("div", { class: "queue-status" }, [_createElementVNode("span", null, [(job.id===queue.active_id)
                  ? (_openBlock(), _createElementBlock("i", { key: 0 }))
                  : _createCommentVNode("", true), _createTextVNode(_toDisplayString(statusText(job.status)), 1)]), (job.id===queue.active_id && job.progress != null)
                  ? (_openBlock(), _createElementBlock("small", { key: 0 }, _toDisplayString(job.progress.toFixed(1)) + "%", 1))
                  : (job.status==='COMPLETE')
                    ? (_openBlock(), _createElementBlock("small", { key: 1 }, _toDisplayString(time(job.elapsed_seconds)) + " · " + _toDisplayString(metric(job.speed_x,1)) + "×", 1))
                    : _createCommentVNode("", true)]),
                (job.status==='COMPLETE')
                  ? (_openBlock(), _createElementBlock("div", {
                      key: 0,
                      class: "row-actions"
                    }, [
                      _createElementVNode("button", {
                        onClick: $event => (copyText(job)),
                        title: "Копировать текст",
                        "aria-label": 'Копировать '+job.name
                      }, "⧉", 8, ["onClick", "aria-label"]),
                      _createElementVNode("button", {
                        onClick: $event => (reveal(job)),
                        title: "Папка результата",
                        "aria-label": 'Папка '+job.name
                      }, "↗", 8, ["onClick", "aria-label"]),
                      _createElementVNode("button", {
                        class: "download-icon",
                        onClick: $event => (download(job)),
                        title: "Скачать Markdown",
                        "aria-label": 'Скачать '+job.name
                      }, "↓", 8, ["onClick", "aria-label"]),
                      _createElementVNode("button", {
                        onClick: $event => (removeJob(job)),
                        title: "Убрать из списка; MD останется на диске",
                        "aria-label": 'Убрать '+job.name
                      }, "×", 8, ["onClick", "aria-label"])
                    ]))
                  : (job.status==='WAITING')
                    ? (_openBlock(), _createElementBlock("div", {
                        key: 1,
                        class: "row-actions"
                      }, [_createElementVNode("button", {
                        onClick: $event => (moveJob(job,-1)),
                        disabled: waiting[0]?.id===job.id,
                        "aria-label": 'Выше '+job.name
                      }, "↑", 8, ["onClick", "disabled", "aria-label"]), _createElementVNode("button", {
                        onClick: $event => (moveJob(job,1)),
                        disabled: waiting[waiting.length-1]?.id===job.id,
                        "aria-label": 'Ниже '+job.name
                      }, "↓", 8, ["onClick", "disabled", "aria-label"]), _createElementVNode("button", {
                        onClick: $event => (removeJob(job)),
                        "aria-label": 'Удалить '+job.name
                      }, "×", 8, ["onClick", "aria-label"])]))
                    : (job.id===queue.active_id)
                      ? (_openBlock(), _createElementBlock("div", {
                          key: 2,
                          class: "row-actions"
                        }, [_createElementVNode("button", {
                          onClick: cancelCurrent,
                          class: "cancel-icon",
                          title: "Отменить текущую",
                          "aria-label": "Отменить текущую обработку"
                        }, "■", 8, ["onClick"])]))
                      : (_openBlock(), _createElementBlock("div", {
                          key: 3,
                          class: "row-actions"
                        }, [(job.status==='SOURCE_MISSING')
                          ? (_openBlock(), _createElementBlock("button", {
                              key: 0,
                              onClick: $event => (locate(job)),
                              title: "Найти исходник"
                            }, "⌕", 8, ["onClick"]))
                          : _createCommentVNode("", true), _createElementVNode("button", {
                          onClick: $event => (retryJob(job)),
                          "aria-label": 'Повторить '+job.name
                        }, "↻", 8, ["onClick", "aria-label"]), _createElementVNode("button", {
                          onClick: $event => (removeJob(job)),
                          "aria-label": 'Удалить '+job.name
                        }, "×", 8, ["onClick", "aria-label"])]))
              ], 42, ["draggable", "onDragstart", "onDragover", "onDrop", "onDragend"]))
            }), 128))])),
        _createElementVNode("div", { class: "queue-toolbar" }, [_createElementVNode("div", { class: "add-controls" }, [_createElementVNode("button", {
          class: "text-button add-button",
          onClick: $event => (nativeFiles('picker')),
          disabled: busyNative || !connected
        }, [_createElementVNode("span", null, "＋"), _createTextVNode(" Добавить файлы")], 8, ["onClick", "disabled"]), _createElementVNode("button", {
          class: "native-drop-button",
          onClick: $event => (nativeFiles('drop')),
          disabled: busyNative || !connected,
          title: "Отдельная Windows-зона для перетаскивания без копий"
        }, "Windows drop ↗", 8, ["onClick", "disabled"])]), _createElementVNode("div", { class: "defaults-controls" }, [_createElementVNode("label", null, [_createTextVNode("МОДЕЛЬ "), _withDirectives(_createElementVNode("select", {
          "onUpdate:modelValue": $event => ((defaultModel) = $event),
          "aria-label": "Модель для новых файлов"
        }, [(_openBlock(true), _createElementBlock(_Fragment, null, _renderList(models, (model) => {
          return (_openBlock(), _createElementBlock("option", {
            key: model.id,
            value: model.id,
            disabled: !model.installed
          }, _toDisplayString(model.name), 9, ["value", "disabled"]))
        }), 128))], 8, ["onUpdate:modelValue"]), [[_vModelSelect, defaultModel]])]), _createElementVNode("label", null, [_createTextVNode("ЯЗЫК "), _withDirectives(_createElementVNode("select", {
          "onUpdate:modelValue": $event => ((defaultLanguage) = $event),
          "aria-label": "Основной язык новых файлов"
        }, [_createElementVNode("option", { value: "auto" }, "AUTO"), _createElementVNode("option", { value: "ru" }, "RU +"), _createElementVNode("option", {
          value: "en",
          disabled: defaultModel==='gigaam'
        }, "EN +", 8, ["disabled"])], 8, ["onUpdate:modelValue"]), [[_vModelSelect, defaultLanguage]])])]), (queue.running && !queue.pause_after_current)
          ? (_openBlock(), _createElementBlock("button", {
              key: 0,
              class: "queue-run secondary-run",
              onClick: $event => (queueAction('pause'))
            }, [_createElementVNode("span", null, "Пауза после текущей"), _createElementVNode("span", null, "Ⅱ")], 8, ["onClick"]))
          : (_openBlock(), _createElementBlock("button", {
              key: 1,
              class: "queue-run",
              onClick: $event => (queueAction('start')),
              disabled: (!waiting.length && !queue.active_id) || !connected || !waitingInstalled
            }, [_createElementVNode("span", null, _toDisplayString(queue.pause_after_current ? 'Продолжить очередь' : 'Запустить очередь'), 1), _createElementVNode("span", null, "↗")], 8, ["onClick", "disabled"]))]),
        _createElementVNode("div", { class: "queue-footnote" }, [_createElementVNode("span", null, _toDisplayString(queue.pause_after_current ? 'Текущая запись завершится. Следующая не начнётся.' : 'Одна модель. Одна задача. Остальные ждут своей очереди.'), 1), _createElementVNode("span", null, _toDisplayString(models.find(m=>m.id===defaultModel)?.note), 1)])
      ])]),
      _createElementVNode("footer", { class: "site-footer" }, [_createElementVNode("span", { class: "footer-brand" }, "SLOI /"), _createElementVNode("span", null, "LOCAL COMPUTE. ORIGINALS UNTOUCHED."), _createElementVNode("span", { class: "footer-right" }, [_createTextVNode(_toDisplayString(connected ? 'СЕАНС АКТИВЕН' : 'СВЯЗЬ ПРЕРВАНА') + " ", 1), _createElementVNode("i", null, "↗")])]),
      dropHover
        ? (_openBlock(), _createElementBlock("div", {
            key: 4,
            class: "drop-overlay",
            onDragover: _withModifiers(() => {}, ["prevent"]),
            onDrop: _withModifiers(onDrop, ["prevent","stop"])
          }, [_createElementVNode("div", null, [_createElementVNode("span", { class: "drop-plus" }, "＋"), _createElementVNode("h2", null, "Отпустите файл"), _createElementVNode("p", null, [_createTextVNode("Для нового исходника Windows попросит подтвердить путь."), _createElementVNode("br"), _createTextVNode("Браузер не загружает и не копирует медиа.")])])], 40, ["onDragover", "onDrop"]))
        : _createCommentVNode("", true)
    ], 40, ["data-theme", "onDragover", "onDragleave", "onDrop", "onKeydown"]))
  }
};})(Vue);
