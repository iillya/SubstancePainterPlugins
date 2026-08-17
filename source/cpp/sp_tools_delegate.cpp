// sp_tools_delegate_qt6.dll
// Substance 3D Painter 属性面板图层工具 —— C++ 界面注入模块（Qt6 / Painter 10.1+）
//
// 职责：
//   * 查找属性面板中的通道按钮（objectName == "channelSelector"）
//   * 在通道按钮行下方注入“每通道 混合模式 + 不透明度”控件面板
//   * 面板被 Painter 重建时自动重新注入（QPointer + 事件过滤器）
//   * 用户改动控件时通过 ctypes 回调通知 Python 写回图层
//
// Python 通过 ctypes 调用本模块：图层数据和映射校准配置由 Python 下发。

#include <QtCore/QCoreApplication>
#include <QtCore/QEvent>
#include <QtCore/QPointer>
#include <QtCore/QSet>
#include <QtCore/QStringList>
#include <QtCore/QTimer>
#include <QtCore/QVector>
#include <QtGui/QCursor>
#include <QtWidgets/QApplication>
#include <QtWidgets/QBoxLayout>
#include <QtWidgets/QComboBox>
#include <QtWidgets/QDockWidget>
#include <QtWidgets/QLabel>
#include <QtWidgets/QLineEdit>
#include <QtWidgets/QMenu>
#include <QtWidgets/QSlider>
#include <QtWidgets/QStackedLayout>
#include <QtWidgets/QStackedWidget>
#include <QtWidgets/QToolButton>
#include <QtWidgets/QWidget>
#include <QtWidgets/QWidgetAction>

#include <windows.h>

namespace {

typedef void (*ValueChangedCallback)(int channelIndex, const wchar_t *modeName,
                                     double opacity);
typedef void (*ResolveChannelsCallback)(int count,
                                        const wchar_t *const *labels,
                                        const wchar_t *const *keys);
typedef void (*ValueRequestCallback)(void);
typedef void (*TextureSettingsCallback)(void);

ValueChangedCallback g_valueCallback = nullptr;
ResolveChannelsCallback g_resolveCallback = nullptr;
ValueRequestCallback g_valueRequestCallback = nullptr;
TextureSettingsCallback g_textureSettingsCallback = nullptr;

struct ChannelInfo {
    QString id;
    QString label;
};

struct BlendModeInfo {
    QString name;
    QString label;
    int value = -1;
};

QVector<ChannelInfo> g_channels;
QVector<BlendModeInfo> g_blendModes;

QPointer<QWidget> g_propertiesPanel;
QPointer<QWidget> g_host;
QPointer<QWidget> g_panelWidget;
QVector<QPointer<QToolButton>> g_blendButtons;
QVector<QPointer<QToolButton>> g_opacityButtons;
QVector<QPointer<QSlider>> g_opacitySliders;
QVector<QPointer<QLineEdit>> g_opacityEdits;
QObject *g_refreshFilter = nullptr;
QObject *g_appFilter = nullptr;
QTimer *g_alignTimer = nullptr;
bool g_refreshPending = false;
bool g_tssPending = false;
bool g_viewPending = false;
bool g_enabled = true;
// 宿主 SP 版本没有 sp.layerstack（如 Painter 7.x）时由 Python 置为 false：
// 禁止注入图层控件面板，但校准助手的过滤器/定时器照常工作。
bool g_layerToolsAvailable = true;
bool g_syncing = false;
bool g_folderMode = false;
bool g_alignEnabled = true;
QSet<QString> g_alignToolIds;
int g_align3A = 1;
int g_align3S = 0;
int g_align2A = 3;
int g_align2S = 2;
QVector<QPointer<QToolButton>> g_alignToolButtons;

void alignNow();

bool isAlignToolButton(QToolButton *button) {
    return button && button->defaultAction() &&
           g_alignToolIds.contains(button->defaultAction()->objectName());
}

void installAlignToolListeners() {
    for (QWidget *widget : QApplication::allWidgets()) {
        auto *button = qobject_cast<QToolButton *>(widget);
        if (!isAlignToolButton(button) || g_alignToolButtons.contains(button))
            continue;
        g_alignToolButtons.append(button);
        QObject::connect(button, &QToolButton::toggled, button, [](bool checked) {
            if (checked)
                alignNow();
        });
    }
    for (int i = g_alignToolButtons.size() - 1; i >= 0; --i) {
        if (!g_alignToolButtons.at(i))
            g_alignToolButtons.remove(i);
    }
}

QString currentAlignToolId() {
    installAlignToolListeners();
    for (const QPointer<QToolButton> &button : g_alignToolButtons) {
        if (button && button->isChecked() && isAlignToolButton(button))
            return button->defaultAction()->objectName();
    }
    return QString();
}

int viewAtCursor() {
    QWidget *current = QApplication::widgetAt(QCursor::pos());
    QSet<QWidget *> visited;
    for (int depth = 0; current && depth < 16; ++depth) {
        if (visited.contains(current))
            break;
        visited.insert(current);
        if (current->objectName() == QStringLiteral("Viewer3D"))
            return 3;
        if (current->objectName() == QStringLiteral("TextureViewer"))
            return 2;
        current = current->parentWidget();
    }
    return 0;
}

void setComboIndex(QComboBox *combo, int target) {
    if (!combo || !combo->isVisible() || combo->currentIndex() == target ||
        target < 0 || target >= combo->count())
        return;
    combo->setCurrentIndex(target);
    QMetaObject::invokeMethod(combo, "activated", Qt::DirectConnection,
                              Q_ARG(int, target));
}

void alignNow() {
    if (!g_enabled || !g_alignEnabled || g_alignToolIds.isEmpty() ||
        currentAlignToolId().isEmpty())
        return;
    const int view = viewAtCursor();
    if (!view)
        return;
    QWidget *toolPanel = nullptr;
    for (QWidget *widget : QApplication::allWidgets()) {
        if (widget->objectName() == QStringLiteral("Tool") &&
            widget->isVisible()) {
            toolPanel = widget;
            break;
        }
    }
    if (!toolPanel)
        return;
    const int targetA = view == 3 ? g_align3A : g_align2A;
    const int targetS = view == 3 ? g_align3S : g_align2S;
    for (QComboBox *combo : toolPanel->findChildren<QComboBox *>()) {
        const QString name = combo->objectName().toLower();
        if (name.contains(QStringLiteral("alignment")))
            setComboIndex(combo, targetA);
        else if (name.contains(QStringLiteral("size_space")))
            setComboIndex(combo, targetS);
    }
}

QString normalized(const QString &text) {
    QString out;
    for (const QChar character : text) {
        const ushort code = character.unicode();
        const bool keep = (code >= 'a' && code <= 'z') ||
                          (code >= '0' && code <= '9') ||
                          (code >= 0x3400 && code <= 0x9fff);
        if (keep)
            out.append(character.toLower());
    }
    return out;
}

QWidget *findPropertiesPanel() {
    for (QWidget *widget : QApplication::allWidgets()) {
        if (auto *dock = qobject_cast<QDockWidget *>(widget)) {
            const QString title = dock->windowTitle();
            if (title.contains(QStringLiteral("属性")) ||
                normalized(title).contains(QStringLiteral("properties")))
                return dock;
        }
    }
    return nullptr;
}

bool isChannelText(const QString &text) {
    // 通道按钮文字（中英文），精确匹配避免误伤“法线贴图细节”这类混合模式名
    const QString clean = normalized(text);
    static const QStringList keys = {
        QStringLiteral("color"), QStringLiteral("basecolor"),
        QStringLiteral("metal"), QStringLiteral("metallic"),
        QStringLiteral("rough"), QStringLiteral("roughness"),
        QStringLiteral("nrm"), QStringLiteral("normal"),
        QStringLiteral("height"), QStringLiteral("emissive"),
        QStringLiteral("ao"),
        QStringLiteral("颜色"), QStringLiteral("金属度"),
        QStringLiteral("粗糙度"), QStringLiteral("法线"), QStringLiteral("高度"),
        QStringLiteral("自发光"), QStringLiteral("环境光遮蔽"),
    };
    return keys.contains(clean);
}

QList<QToolButton *> findChannelButtons(QWidget *panel) {
    QList<QToolButton *> result;
    QSet<QWidget *> channelRows;
    QList<QToolButton *> known;
    for (QToolButton *button : panel->findChildren<QToolButton *>()) {
        if (!button->isVisible())
            continue;
        if (button->text().trimmed().isEmpty())
            continue;
        // 图层用 objectName=channelSelector；滤镜/生成器用通道文字（如 color）识别
        if (button->objectName() == QStringLiteral("channelSelector") ||
            isChannelText(button->text())) {
            known.append(button);
            if (button->parentWidget())
                channelRows.insert(button->parentWidget());
        }
    }
    // 通道行里的全部按钮都算通道按钮（含自定义通道，如 abs col / CoatColor）
    for (QWidget *row : channelRows) {
        for (QObject *child : row->children()) {
            auto *button = qobject_cast<QToolButton *>(child);
            if (!button)
                continue;
            if (!button->isVisible())
                continue;
            if (button->text().trimmed().isEmpty())
                continue;
            if (!result.contains(button))
                result.append(button);
        }
    }
    // 兜底：已知按钮若不在已识别行中，也加入
    for (QToolButton *button : known) {
        if (!result.contains(button))
            result.append(button);
    }
    if (result.isEmpty())
        return result;
    std::sort(result.begin(), result.end(),
              [](QToolButton *a, QToolButton *b) {
                  return a->geometry().x() < b->geometry().x();
              });
    return result;
}

QComboBox *findLayerChannelCombo() {
    for (QWidget *widget : QApplication::allWidgets()) {
        auto *dock = qobject_cast<QDockWidget *>(widget);
        if (!dock)
            continue;
        const QString title = dock->windowTitle();
        if (!title.contains(QStringLiteral("图层")) &&
            !normalized(title).contains(QStringLiteral("layers")))
            continue;
        for (QComboBox *combo : dock->findChildren<QComboBox *>()) {
            if (combo->objectName() == QStringLiteral("channelSelector") &&
                combo->isVisible())
                return combo;
        }
    }
    return nullptr;
}

void requestChannelResolution() {
    if (!g_resolveCallback)
        return;
    QComboBox *combo = findLayerChannelCombo();
    if (!combo) {
        g_resolveCallback(0, nullptr, nullptr);
        return;
    }
    QVector<QString> labels;
    QVector<QString> keys;
    QVector<const wchar_t *> labelPointers;
    QVector<const wchar_t *> keyPointers;
    labels.reserve(combo->count());
    keys.reserve(combo->count());
    labelPointers.reserve(combo->count());
    keyPointers.reserve(combo->count());
    for (int i = 0; i < combo->count(); ++i) {
        labels.append(combo->itemText(i));
        keys.append(combo->itemData(i).toString());
    }
    for (int i = 0; i < labels.size(); ++i) {
        labelPointers.append(
            reinterpret_cast<const wchar_t *>(labels.at(i).utf16()));
        keyPointers.append(
            reinterpret_cast<const wchar_t *>(keys.at(i).utf16()));
    }
    g_resolveCallback(labels.size(), labelPointers.constData(),
                      keyPointers.constData());
}

void applyReferenceStyle(QWidget *propertiesPanel, QToolButton *blendButton,
                         QToolButton *opacityButton, QSlider *slider) {
    // 从面板中原生的深色下拉框复制调色板，保证与 Painter 主题一致
    QPalette reference = QApplication::palette();
    if (propertiesPanel) {
        for (QComboBox *nativeCombo : propertiesPanel->findChildren<QComboBox *>()) {
            if (!nativeCombo->isVisible())
                continue;
            if (nativeCombo->objectName().startsWith(QStringLiteral("sp_tools")))
                continue;
            reference = nativeCombo->palette();
            break;
        }
    }
    blendButton->setPalette(reference);
    opacityButton->setPalette(reference);
    slider->setPalette(reference);
}

QMenu *findNativeBlendMenu() {
    for (QWidget *widget : QApplication::allWidgets()) {
        if (auto *dock = qobject_cast<QDockWidget *>(widget)) {
            const QString title = dock->windowTitle();
            if (!title.contains(QStringLiteral("图层")) &&
                !normalized(title).contains(QStringLiteral("layers")))
                continue;
            for (QToolButton *button : dock->findChildren<QToolButton *>()) {
                if (button->objectName() != QStringLiteral("blendingMode"))
                    continue;
                if (!button->isVisible())
                    continue;
                if (QMenu *menu = button->menu())
                    return menu;
            }
        }
    }
    return nullptr;
}

QWidget *buildPanel(int rowHeight, QWidget *propertiesPanel) {
    auto *panel = new QWidget();
    panel->setObjectName(QStringLiteral("sp_tools_channel_panel"));
    // 只占内容高度，避免被宿主布局拉高导致行距显得松散
    panel->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Maximum);
    auto *vbox = new QVBoxLayout(panel);
    vbox->setContentsMargins(0, 4, 0, 4);
    vbox->setSpacing(4);
    g_blendButtons.clear();
    g_opacityButtons.clear();
    g_opacitySliders.clear();
    g_opacityEdits.clear();
    // 原生混合模式菜单只需查一次，供所有行克隆
    QMenu *nativeMenu = findNativeBlendMenu();

    for (int i = 0; i < g_channels.size(); ++i) {
        // 每行包在一个固定纵向尺寸的容器里：面板被拉高时，行不会跟着伸展，
        // 多余高度由面板末尾的伸缩项吸收，行始终紧凑排列在顶部。
        auto *rowWidget = new QWidget(panel);
        rowWidget->setObjectName(QStringLiteral("sp_tools_channel_row"));
        rowWidget->setSizePolicy(QSizePolicy::Preferred, QSizePolicy::Fixed);
        auto *row = new QHBoxLayout(rowWidget);
        // 每行前后（左右）留一点距离：仅文件夹模式，其他图层保持原样
        row->setContentsMargins(g_folderMode ? 16 : 0, 0,
                                g_folderMode ? 16 : 0, 0);
        row->setSpacing(4);
        auto *label = new QLabel(g_channels[i].label);
        label->setMinimumWidth(56);
        label->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        // 混合模式：与图层面板一致 —— QToolButton('blendingMode') + blendingModeMenu
        auto *blendButton = new QToolButton();
        blendButton->setObjectName(QStringLiteral("blendingMode"));
        blendButton->setPopupMode(QToolButton::InstantPopup);
        blendButton->setFixedHeight(rowHeight > 0 ? rowHeight : 22);
        blendButton->setMinimumWidth(92);
        blendButton->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        blendButton->setText(QStringLiteral("正常"));
        blendButton->setProperty("sp_tools_mode_name", QString());
        auto *blendMenu = new QMenu(blendButton);
        blendMenu->setObjectName(QStringLiteral("blendingModeMenu"));
        // 与图层面板原生混合模式菜单保持一致：复制顺序、分隔线、文字
        if (nativeMenu) {
            for (QAction *nativeAction : nativeMenu->actions()) {
                if (nativeAction->isSeparator()) {
                    blendMenu->addSeparator();
                    continue;
                }
                QAction *ourAction = blendMenu->addAction(nativeAction->text());
                QString modeName;
                bool ok = false;
                const int nativeValue = nativeAction->data().toInt(&ok);
                if (ok) {
                    for (const BlendModeInfo &mode : g_blendModes) {
                        if (mode.value == nativeValue) {
                            modeName = mode.name;
                            break;
                        }
                    }
                }
                if (modeName.isEmpty()) {
                    for (const BlendModeInfo &mode : g_blendModes) {
                        if (mode.label == nativeAction->text()) {
                            modeName = mode.name;
                            break;
                        }
                    }
                }
                ourAction->setData(modeName);
            }
        } else {
            for (const BlendModeInfo &mode : g_blendModes)
                blendMenu->addAction(mode.label)->setData(mode.name);
        }
        blendButton->setMenu(blendMenu);

        // 不透明度：与图层面板一致 —— 标题 + 数值输入 + 滑块
        auto *opacityButton = new QToolButton();
        opacityButton->setObjectName(QStringLiteral("opacity"));
        opacityButton->setPopupMode(QToolButton::InstantPopup);
        opacityButton->setFixedHeight(rowHeight > 0 ? rowHeight : 22);
        opacityButton->setMinimumWidth(52);
        opacityButton->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        opacityButton->setText(QStringLiteral("100"));
        auto *opacityMenu = new QMenu(opacityButton);
        opacityMenu->setObjectName(QStringLiteral("opacityMenu"));
        auto *sliderAction = new QWidgetAction(opacityMenu);
        auto *opacityWidget = new QWidget();
        auto *opacityVbox = new QVBoxLayout(opacityWidget);
        opacityVbox->setContentsMargins(6, 4, 6, 4);
        opacityVbox->setSpacing(4);
        auto *header = new QHBoxLayout();
        header->setSpacing(6);
        auto *opacityTitle = new QLabel(QStringLiteral("不透明度"));
        auto *opacityEdit = new QLineEdit(QStringLiteral("100"));
        opacityEdit->setObjectName(QStringLiteral("opacityValueEdit"));
        opacityEdit->setFixedWidth(48);
        opacityEdit->setAlignment(Qt::AlignRight);
        header->addWidget(opacityTitle);
        header->addStretch(1);
        header->addWidget(opacityEdit);
        opacityVbox->addLayout(header);
        auto *opacitySlider = new QSlider(Qt::Horizontal);
        opacitySlider->setObjectName(QStringLiteral("slider_"));
        opacitySlider->setRange(0, 100);
        opacitySlider->setFixedWidth(180);
        opacityVbox->addWidget(opacitySlider);
        sliderAction->setDefaultWidget(opacityWidget);
        opacityMenu->addAction(sliderAction);
        opacityButton->setMenu(opacityMenu);
        row->addWidget(label, 3);
        row->addWidget(blendButton, 5);
        row->addWidget(opacityButton, 2);
        vbox->addWidget(rowWidget);
        g_blendButtons.append(blendButton);
        g_opacityButtons.append(opacityButton);
        g_opacitySliders.append(opacitySlider);
        g_opacityEdits.append(opacityEdit);
        applyReferenceStyle(propertiesPanel, blendButton, opacityButton,
                            opacitySlider);

        const int index = i;
        QObject::connect(blendMenu, &QMenu::triggered, panel,
                         [index](QAction *action) {
            QToolButton *blendButton = g_blendButtons.value(index);
            const QString modeName = action->data().toString();
            if (blendButton) {
                blendButton->setText(action->text());
                blendButton->setProperty("sp_tools_mode_name", modeName);
            }
            if (g_syncing || !g_valueCallback)
                return;
            QSlider *slider = g_opacitySliders.value(index);
            g_valueCallback(index, modeName.toStdWString().c_str(),
                            slider ? slider->value() : 0);
        });
        QObject::connect(opacitySlider, &QSlider::valueChanged, panel,
                         [index, opacityEdit](int value) {
            QToolButton *button = g_opacityButtons.value(index);
            if (button)
                button->setText(QString::number(value));
            opacityEdit->setText(QString::number(value));
            if (g_syncing || !g_valueCallback)
                return;
            QToolButton *blendButton = g_blendButtons.value(index);
            if (!blendButton)
                return;
            const QString modeName =
                blendButton->property("sp_tools_mode_name").toString();
            g_valueCallback(index, modeName.toStdWString().c_str(), value);
        });
        QObject::connect(opacityEdit, &QLineEdit::editingFinished, panel,
                         [index, opacitySlider, opacityEdit]() {
            bool ok = false;
            const int value = opacityEdit->text().trimmed().toInt(&ok);
            if (!ok)
                opacityEdit->setText(QString::number(opacitySlider->value()));
            else
                opacitySlider->setValue(qBound(0, value, 100));
        });
    }
    // 末尾伸缩项吸收面板剩余高度，行始终紧凑排列在顶部
    vbox->addStretch(1);
    return panel;
}

QString modeLabelForName(const QString &name) {
    for (const BlendModeInfo &mode : g_blendModes)
        if (mode.name == name)
            return mode.label;
    return QString();
}

// 统一挂载入口：填充/绘画图层与文件夹都复用 buildPanel 创建面板，
// 唯一差异是调用方传入的宿主、布局与插入位置（锚点）。
void attachPanel(QWidget *panelWidget, QLayout *layout, int insertAt) {
    if (auto *box = qobject_cast<QBoxLayout *>(layout)) {
        if (insertAt >= 0 && insertAt <= box->count())
            box->insertWidget(insertAt, panelWidget);
        else
            box->addWidget(panelWidget);
        return;
    }
    if (auto *stackLayout = qobject_cast<QStackedLayout *>(layout)) {
        // 极少见的兜底：内容区本身是堆叠布局时，作为最前页显示
        stackLayout->addWidget(panelWidget);
        stackLayout->setCurrentWidget(panelWidget);
        return;
    }
    layout->addWidget(panelWidget);
}

void removePanel() {
    if (g_panelWidget) {
        if (QWidget *oldParent = g_panelWidget->parentWidget()) {
            if (QLayout *oldLayout = oldParent->layout())
                oldLayout->removeWidget(g_panelWidget);
        }
        g_panelWidget->deleteLater();
        g_panelWidget = nullptr;
    }
}

bool onPanelRefresh();
bool inject();

class PanelRefreshFilter final : public QObject {
public:
    using QObject::QObject;

protected:
    bool eventFilter(QObject *obj, QEvent *event) override {
        if (!g_enabled)
            return false;
        const QEvent::Type type = event->type();
        if (type != QEvent::Show && type != QEvent::Polish &&
            type != QEvent::LayoutRequest && type != QEvent::Resize &&
            // 参照翻译插件：Paint 是宿主重建/改写控件后的最后兜底信号。
            type != QEvent::Paint)
            return false;
        if (!isInsidePropertiesPanel(obj))
            return false;
        if (!g_refreshPending) {
            g_refreshPending = true;
            QTimer::singleShot(0, [] {
                g_refreshPending = false;
                onPanelRefresh();
            });
        }
        return false;
    }

private:
    static bool isInsidePropertiesPanel(QObject *obj) {
        if (!obj || !g_propertiesPanel)
            return false;
        QWidget *targetWindow = g_propertiesPanel->window();
        for (QObject *current = obj; current; current = current->parent()) {
            if (current == g_propertiesPanel)
                return true;
            if (current->isWidgetType()) {
                QWidget *widget = static_cast<QWidget *>(current);
                if (widget->window() != targetWindow)
                    return false;
            }
        }
        return false;
    }
};

// 纹理集设置面板级过滤器：面板打开后挂在控件自身，监听其刷新（不监听 Hide，
// 避免销毁期回调）。
class TextureSetSettingsFilter final : public QObject {
public:
    explicit TextureSetSettingsFilter(QWidget *widget) : QObject(widget) {}

protected:
    bool eventFilter(QObject *obj, QEvent *event) override {
        (void)obj;
        if (!g_enabled)
            return false;
        const QEvent::Type type = event->type();
        if (type != QEvent::Polish && type != QEvent::LayoutRequest &&
            type != QEvent::Resize && type != QEvent::Paint)
            return false;
        if (!g_tssPending) {
            g_tssPending = true;
            QTimer::singleShot(0, [] {
                g_tssPending = false;
                if (g_textureSettingsCallback)
                    g_textureSettingsCallback();
            });
        }
        return false;
    }
};

// 应用级触发器：Show 发现纹理集设置面板（挂面板级过滤器 + 立即检查一次通道），
// Enter/Leave 检测 3D/2D 视图进出（触发校准同步）。
class AppTriggerFilter final : public QObject {
public:
    using QObject::QObject;

protected:
    bool eventFilter(QObject *obj, QEvent *event) override {
        if (!g_enabled)
            return false;
        const QEvent::Type type = event->type();
        if (type == QEvent::Show) {
            if (isTextureSetSettings(obj)) {
                auto *widget = static_cast<QWidget *>(obj);
                if (widget != m_tssWidget) {
                    m_tssWidget = widget;
                    m_tssFilter = new TextureSetSettingsFilter(widget);
                    widget->installEventFilter(m_tssFilter);
                }
                if (!g_tssPending) {
                    g_tssPending = true;
                    QTimer::singleShot(0, [] {
                        g_tssPending = false;
                        if (g_textureSettingsCallback)
                            g_textureSettingsCallback();
                    });
                }
            }
        } else if (type == QEvent::Enter || type == QEvent::Leave) {
            if (isInsideView(obj)) {
                if (!g_viewPending) {
                    g_viewPending = true;
                    QTimer::singleShot(0, [] {
                        g_viewPending = false;
                        alignNow();
                    });
                }
            }
        }
        return false;
    }

private:
    static bool isTextureSetSettings(QObject *obj) {
        if (!obj || !obj->isWidgetType())
            return false;
        QWidget *widget = static_cast<QWidget *>(obj);
        if (widget->objectName() == QStringLiteral("textureSetSettings"))
            return true;
        const QString title = widget->windowTitle();
        return title.contains(QStringLiteral("纹理集设置")) ||
               normalized(title).contains(QStringLiteral("texturesetsettings"));
    }

    static bool isInsideView(QObject *obj) {
        int depth = 0;
        for (QObject *current = obj; current && depth < 16;
             current = current->parent(), ++depth) {
            if (!current->isWidgetType())
                continue;
            const QString name = static_cast<QWidget *>(current)->objectName();
            if (name == QStringLiteral("Viewer3D") ||
                name == QStringLiteral("TextureViewer"))
                return true;
        }
        return false;
    }

    // 用 QPointer 持有：面板销毁时自动置空，避免地址复用后继续使用悬垂过滤器
    QPointer<QWidget> m_tssWidget;
    QPointer<TextureSetSettingsFilter> m_tssFilter;
};

bool onPanelRefresh() {
    if (!g_enabled)
        return false;
    // 只负责“面板被 Painter 重建后恢复注入”，不在这里重建/刷数值（节省性能）。
    // 切换图层、新建通道的重建由 Python 事件驱动。
    if (!g_panelWidget)
        inject();
    return true;
}

bool inject() {
    if (!g_enabled || !g_layerToolsAvailable)
        return false;
    QWidget *panel = findPropertiesPanel();
    if (!panel)
        return false;
    const QList<QToolButton *> buttons = findChannelButtons(panel);
    if (buttons.isEmpty() && !g_folderMode)
        return false;

    if (!buttons.isEmpty()) {
        // 通道列表由 Python 按 all_channels() 全量下发（行数=通道数）；
        // 按钮只用来定位插入锚点，数量与通道数不需要一致。
        if (g_channels.isEmpty()) {
            requestChannelResolution();
            if (g_channels.isEmpty())
                return false;
        }
    } else {
        // 文件夹模式：属性面板没有通道按钮，通道列表由 Python 按纹理集下发
        if (g_channels.isEmpty()) {
            requestChannelResolution();
            if (g_channels.isEmpty())
                return false;
        }
    }

    QWidget *container = nullptr;
    QWidget *host = nullptr;
    QLayout *layout = nullptr;
    int insertAt = -1;
    if (buttons.isEmpty()) {
        // 文件夹：与填充/绘画图层同一套挂载，只把锚点换成属性面板内容区顶部。
        QWidget *contentWidget = nullptr;
        if (auto *dock = qobject_cast<QDockWidget *>(panel))
            contentWidget = dock->widget();
        host = contentWidget ? contentWidget : panel;
        if (!host)
            return false;
        // 若内容区本身是堆叠容器（QStackedWidget 或带 QStackedLayout），
        // 取当前页作为锚点：面板插进页内、贴内容高度，而不是整页占满。
        if (auto *stacked = qobject_cast<QStackedWidget *>(host)) {
            if (QWidget *current = stacked->currentWidget())
                host = current;
        } else if (auto *stackLayout =
                       qobject_cast<QStackedLayout *>(host->layout())) {
            if (QWidget *current = stackLayout->currentWidget())
                host = current;
        }
        layout = host->layout();
        if (!layout) {
            auto *vbox = new QVBoxLayout(host);
            vbox->setContentsMargins(0, 0, 0, 0);
            vbox->setSpacing(0);
            layout = vbox;
        }
        insertAt = 0;
        // SP 自带的空状态提示（QLabel objectName=layer-no-properties，
        // 文字“未发现任何属性”）：把我们的面板放到它下面
        for (QLabel *label : host->findChildren<QLabel *>()) {
            if (!label->isVisible())
                continue;
            const QString text = label->text().trimmed();
            const bool isEmptyHint =
                label->objectName() == QStringLiteral("layer-no-properties") ||
                text.contains(QStringLiteral("未发现")) ||
                normalized(text).contains(QStringLiteral("nopropert")) ||
                normalized(text).contains(QStringLiteral("nothing"));
            if (!isEmptyHint)
                continue;
            // 提示可能直接是宿主布局的子项，也可能包在一层行容器里
            int idx = layout->indexOf(label);
            if (idx < 0) {
                QWidget *row = label->parentWidget();
                for (int depth = 0; row && row != host && depth < 8; ++depth) {
                    idx = layout->indexOf(row);
                    if (idx >= 0)
                        break;
                    row = row->parentWidget();
                }
            }
            if (idx >= 0) {
                insertAt = idx + 1;
                break;
            }
        }
    } else {
        container = buttons.first()->parentWidget();
        if (!container)
            return false;
        host = container->parentWidget();
        if (!host)
            return false;
        layout = host->layout();
        if (!layout)
            return false;
        insertAt = layout->indexOf(container) + 1;
    }

    // 已注入且仍然挂在目标宿主上
    if (g_panelWidget && g_host == host && g_panelWidget->parentWidget())
        return true;

    // 移除旧的（如果还在）
    if (g_panelWidget) {
        if (QWidget *oldParent = g_panelWidget->parentWidget()) {
            if (QLayout *oldLayout = oldParent->layout())
                oldLayout->removeWidget(g_panelWidget);
        }
        g_panelWidget->deleteLater();
        g_panelWidget = nullptr;
    }

    int rowHeight = 0;
    for (const QToolButton *button : buttons)
        rowHeight = qMax(rowHeight, button->height());

    QWidget *panelWidget = buildPanel(rowHeight, panel);
    attachPanel(panelWidget, layout, insertAt);
    panelWidget->show();
    g_panelWidget = panelWidget;
    g_host = host;
    g_propertiesPanel = panel;
    // 控件就绪后主动向 Python 请求当前图层各通道的值
    if (g_valueRequestCallback)
        g_valueRequestCallback();
    return true;
}

bool pinThisDll() {
    HMODULE module = nullptr;
    return GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
            GET_MODULE_HANDLE_EX_FLAG_PIN,
        reinterpret_cast<LPCWSTR>(&pinThisDll), &module) != 0;
}

} // namespace

extern "C" __declspec(dllexport) int __cdecl sp_tools_api_version() {
    return 7;
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_enabled(int enabled) {
    g_enabled = enabled != 0;
    if (g_panelWidget)
        g_panelWidget->setVisible(g_enabled);
    if (g_enabled)
        inject();
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_layer_tools_available(int available) {
    g_layerToolsAvailable = available != 0;
    if (!g_layerToolsAvailable) {
        removePanel();
        g_channels.clear();
    }
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_value_callback(ValueChangedCallback callback) {
    g_valueCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_resolve_callback(ResolveChannelsCallback callback) {
    g_resolveCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_value_request_callback(ValueRequestCallback callback) {
    g_valueRequestCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl
sp_tools_set_texture_settings_callback(TextureSettingsCallback callback) {
    g_textureSettingsCallback = callback;
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_align_config(
    int enabled, int toolCount, const wchar_t *const *toolIds,
    int align3A, int align3S, int align2A, int align2S) {
    g_alignEnabled = enabled != 0;
    g_alignToolIds.clear();
    for (int i = 0; i < toolCount; ++i) {
        if (toolIds && toolIds[i])
            g_alignToolIds.insert(QString::fromWCharArray(toolIds[i]));
    }
    g_align3A = align3A;
    g_align3S = align3S;
    g_align2A = align2A;
    g_align2S = align2S;
    installAlignToolListeners();
    alignNow();
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_blend_modes(
    int count, const wchar_t *const *names, const wchar_t *const *labels,
    const int *values) {
    g_blendModes.clear();
    for (int i = 0; i < count; ++i) {
        BlendModeInfo info;
        info.name = names && names[i] ? QString::fromWCharArray(names[i])
                                      : QString();
        info.label = labels && labels[i] ? QString::fromWCharArray(labels[i])
                                         : info.name;
        info.value = values ? values[i] : -1;
        g_blendModes.append(info);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_channels(
    int count, const wchar_t *const *ids, const wchar_t *const *labels) {
    g_channels.clear();
    for (int i = 0; i < count; ++i) {
        ChannelInfo info;
        info.id = ids && ids[i] ? QString::fromWCharArray(ids[i]) : QString();
        info.label = labels && labels[i] ? QString::fromWCharArray(labels[i])
                                         : info.id;
        g_channels.append(info);
    }
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_value(
    int index, const wchar_t *modeName, double opacity) {
    if (index < 0 || index >= g_blendButtons.size())
        return;
    QToolButton *blendButton = g_blendButtons.value(index);
    QToolButton *button = g_opacityButtons.value(index);
    QSlider *slider = g_opacitySliders.value(index);
    QLineEdit *edit = g_opacityEdits.value(index);
    if (!blendButton || !button || !slider)
        return;
    const QString mode = modeName ? QString::fromWCharArray(modeName)
                                  : QString();
    const bool valid = !mode.isEmpty() && opacity >= 0.0;
    g_syncing = true;
    const QString label = modeLabelForName(mode);
    if (!label.isEmpty()) {
        blendButton->setText(label);
        blendButton->setProperty("sp_tools_mode_name", mode);
    }
    if (opacity >= 0.0) {
        const int value = qBound(0, qRound(opacity), 100);
        slider->setValue(value);
        button->setText(QString::number(value));
        if (edit)
            edit->setText(QString::number(value));
    }
    blendButton->setEnabled(valid);
    button->setEnabled(valid);
    slider->setEnabled(valid);
    if (edit)
        edit->setEnabled(valid);
    g_syncing = false;
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_reinject() {
    removePanel();
    inject();
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_request_channels() {
    requestChannelResolution();
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_shutdown() {
    // 关闭时先把 C++ 持有的 Python 回调全部清空并移除面板，
    // 保证退出阶段不会调用到已被 Python 释放的回调（python311 崩溃点）。
    g_enabled = false;
    g_layerToolsAvailable = true;
    g_valueCallback = nullptr;
    g_resolveCallback = nullptr;
    g_valueRequestCallback = nullptr;
    g_textureSettingsCallback = nullptr;
    // 工具按钮连接以按钮自身为 context。热重载时保留 QPointer 列表，避免
    // 下一次 install 重复连接；已销毁按钮会在下一轮扫描中自动清除。
    if (g_refreshFilter) {
        if (QCoreApplication::instance())
            QCoreApplication::instance()->removeEventFilter(g_refreshFilter);
        delete g_refreshFilter;
        g_refreshFilter = nullptr;
    }
    if (g_appFilter) {
        if (QCoreApplication::instance())
            QCoreApplication::instance()->removeEventFilter(g_appFilter);
        delete g_appFilter;
        g_appFilter = nullptr;
    }
    if (g_alignTimer) {
        g_alignTimer->stop();
        delete g_alignTimer;
        g_alignTimer = nullptr;
    }
    removePanel();
}

extern "C" __declspec(dllexport) void __cdecl sp_tools_set_folder_mode(int enabled) {
    const bool folder = enabled != 0;
    if (folder == g_folderMode)
        return;
    g_folderMode = folder;
    if (folder)
        g_channels.clear();
    sp_tools_reinject();
}

extern "C" __declspec(dllexport) int __cdecl sp_tools_install(void *appPtr) {
    pinThisDll();
    QApplication *application =
        appPtr ? reinterpret_cast<QApplication *>(appPtr) : nullptr;
    if (!application)
        application = qobject_cast<QApplication *>(QCoreApplication::instance());
    if (!application)
        return 0;
    // Painter 退出时禁用插件并移除事件过滤器，避免在控件销毁过程中
    // 继续访问 UI（否则退出时会崩溃）。
    static bool quitHookConnected = false;
    if (!quitHookConnected) {
        quitHookConnected = true;
        QObject::connect(application, &QCoreApplication::aboutToQuit, [] {
            g_enabled = false;
            g_valueCallback = nullptr;
            g_resolveCallback = nullptr;
            g_valueRequestCallback = nullptr;
            g_textureSettingsCallback = nullptr;
            g_alignToolButtons.clear();
            if (g_refreshFilter) {
                QCoreApplication::instance()->removeEventFilter(g_refreshFilter);
                delete g_refreshFilter;
                g_refreshFilter = nullptr;
            }
            if (g_appFilter) {
                QCoreApplication::instance()->removeEventFilter(g_appFilter);
                delete g_appFilter;
                g_appFilter = nullptr;
            }
            if (g_alignTimer) {
                g_alignTimer->stop();
                delete g_alignTimer;
                g_alignTimer = nullptr;
            }
            removePanel();
        });
    }
    if (!g_refreshFilter) {
        g_refreshFilter = new PanelRefreshFilter();
        application->installEventFilter(g_refreshFilter);
    }
    if (!g_appFilter) {
        g_appFilter = new AppTriggerFilter();
        application->installEventFilter(g_appFilter);
    }
    if (!g_alignTimer) {
        g_alignTimer = new QTimer(application);
        // 映射校准采用简单的 200ms 实际值核对；只有值不一致时才写入。
        g_alignTimer->setInterval(200);
        QObject::connect(g_alignTimer, &QTimer::timeout, [] { alignNow(); });
        g_alignTimer->start();
    }
    inject();
    return 1;
}
