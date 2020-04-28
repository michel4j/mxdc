from mxdc import Registry, IBeamline, Object, Property
from datetime import datetime
from gi.repository import Gtk, Gio, Gdk, GdkPixbuf

from mxdc.utils import gui, misc, colors

AVATAR_SIZE = 50


class Message(Object):

    user = Property(type=str, default='')
    message = Property(type=str, default='')
    date = Property(type=str, default='')
    avatar = Property(type=int, default=0)

    def __init__(self, user, avatar, message, date):
        super().__init__()
        self.props.user = user
        self.props.avatar = avatar
        self.props.message = message
        self.props.date = date

    def update(self, user, avatar, message, date):
        self.props.user = user
        self.props.avatar = avatar
        self.props.message = message
        self.props.date = date

    def get_info(self):
        return {
            'user': self.user,
            'avatar': self.avatar,
            'message': self.message,
            'date': self.date,
        }


class ChatMessageLTR(gui.Builder):
    gui_roots = {
        'data/chat-ltr': ['message_row']
    }

    def get_widget(self):
        row = Gtk.ListBoxRow()
        row.get_style_context().add_class('chat-row')
        row.add(self.message_row)
        self.update()
        return row

    def set_item(self, item):
        self.item = item
        for param in ['user', 'avatar', 'message', 'date']:
            self.item.connect('notify::{}'.format(param), self.update)

    def update(self, *args, **kwargs):
        col = Gdk.RGBA(alpha=0.2)
        col.parse(colors.Category.CAT10[misc.NameToInt.get(self.item.props.user) % 10])
        self.chat_message.override_background_color(Gtk.StateType.NORMAL, col)
        self.user_lbl.set_text(self.item.props.user)
        self.message_lbl.set_text(self.item.props.message)
        self.date_lbl.set_text(self.item.props.date)

        avatar = GdkPixbuf.Pixbuf.new_from_resource_at_scale(
            AVATAR_SIZE, AVATAR_SIZE,
            f'/org/mxdc/data/avatar/user-{self.item.props.avatar}.svg',
            True,
        )
        self.user_icon.set_from_pixbuf(avatar)


class ChatMessageRTL(ChatMessageLTR):
    gui_roots = {
        'data/chat-rtl': ['message_row']
    }


class ChatController(object):
    def __init__(self, widget):
        self.widget = widget
        self.beamline = Registry.get_utility(IBeamline)
        self.messages = Gio.ListStore(item_type=Message)
        self.widget.chat_messages.bind_model(self.messages, self.create_message)
        self.widget.chat_user_fbk.set_text(misc.get_project_name())
        self.widget.chat_send_btn.connect('clicked', self.send_message)
        self.widget.chat_msg_entry.connect('activate', self.send_message)
        self.widget.chat_messages.connect('size-allocate', self.adjust_view)
        self.beamline.messenger.connect('message', self.show_message)

    def create_message(self, item):
        if item.user == misc.get_project_name():
            config = ChatMessageLTR()
        else:
            config = ChatMessageRTL()
        config.set_item(item)
        return config.get_widget()

    def show_message(self, client, user, message):
        item = Message(
            user,
            0,
            message,
            datetime.now().strftime('%b/%d, %H:%M')
        )
        self.messages.append(item)

        vis_page = self.widget.main_stack.get_visible_child_name()
        if vis_page != 'Chat':
            self.widget.notifier.notify('New Message from {}: {}'.format(user, message), duration=10)
            chat_page = self.widget.main_stack.get_child_by_name('Chat')
            self.widget.setup_status_stack.child_set(chat_page, needs_attention=True)

    def adjust_view(self, widget, event, data=None):
        adj = widget.get_adjustment()
        adj.set_value(adj.get_upper() - adj.get_page_size())

    def send_message(self, *args, **kwargs):
        msg = self.widget.chat_msg_entry.get_text()
        if msg:
            self.beamline.messenger.send(msg)
            self.widget.chat_msg_entry.set_text('')

