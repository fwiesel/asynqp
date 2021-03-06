import asyncio
import asynqp
import socket
import contexts
from .util import testing_exception_handler


class ConnectionContext:
    def given_a_connection(self):
        self.loop = asyncio.get_event_loop()
        self.connection = self.loop.run_until_complete(asyncio.wait_for(asynqp.connect(), 0.2))

    def cleanup_the_connection(self):
        self.loop.run_until_complete(asyncio.wait_for(self.connection.close(), 0.2))


class ChannelContext(ConnectionContext):
    def given_a_channel(self):
        self.channel = self.loop.run_until_complete(asyncio.wait_for(self.connection.open_channel(), 0.2))

    def cleanup_the_channel(self):
        self.loop.run_until_complete(asyncio.wait_for(self.channel.close(), 0.2))


class BoundQueueContext(ChannelContext):
    def given_a_queue_bound_to_an_exchange(self):
        self.loop.run_until_complete(asyncio.wait_for(self.setup(), 0.4))

    def cleanup_the_queue_and_exchange(self):
        self.loop.run_until_complete(asyncio.wait_for(self.teardown(), 0.2))

    @asyncio.coroutine
    def setup(self):
        self.queue = yield from self.channel.declare_queue('my.queue', exclusive=True)
        self.exchange = yield from self.channel.declare_exchange('my.exchange', 'fanout')

        yield from self.queue.bind(self.exchange, 'doesntmatter')

    @asyncio.coroutine
    def teardown(self):
        yield from self.queue.delete(if_unused=False, if_empty=False)
        yield from self.exchange.delete(if_unused=False)


class WhenConnectingToRabbit:
    def given_the_loop(self):
        self.loop = asyncio.get_event_loop()

    def when_I_connect(self):
        self.connection = self.loop.run_until_complete(asyncio.wait_for(asynqp.connect(), 0.2))

    def it_should_connect(self):
        assert self.connection is not None

    def cleanup_the_connection(self):
        self.loop.run_until_complete(asyncio.wait_for(self.connection.close(), 0.2))


class WhenConnectingToRabbitWithAnExistingSocket:
    def given_the_loop(self):
        self.loop = asyncio.get_event_loop()
        self.sock = socket.create_connection(("localhost", 5672))

    def when_I_connect(self):
        self.connection = self.loop.run_until_complete(asyncio.wait_for(asynqp.connect(sock=self.sock), 0.2))

    def it_should_connect(self):
        assert self.connection is not None

    def cleanup_the_connection(self):
        self.loop.run_until_complete(asyncio.wait_for(self.connection.close(), 0.2))
        self.sock.close()


class WhenOpeningAChannel(ConnectionContext):
    def when_I_open_a_channel(self):
        self.channel = self.loop.run_until_complete(asyncio.wait_for(self.connection.open_channel(), 0.2))

    def it_should_give_me_the_channel(self):
        assert self.channel is not None

    def cleanup_the_channel(self):
        self.loop.run_until_complete(asyncio.wait_for(self.channel.close(), 0.2))


class WhenDeclaringAQueue(ChannelContext):
    def when_I_declare_a_queue(self):
        self.queue = self.loop.run_until_complete(asyncio.wait_for(self.channel.declare_queue('my.queue', exclusive=True), 0.2))

    def it_should_have_the_correct_queue_name(self):
        assert self.queue.name == 'my.queue'

    def cleanup_the_queue(self):
        self.loop.run_until_complete(asyncio.wait_for(self.queue.delete(if_unused=False, if_empty=False), 0.2))


class WhenDeclaringAnExchange(ChannelContext):
    def when_I_declare_an_exchange(self):
        self.exchange = self.loop.run_until_complete(asyncio.wait_for(self.channel.declare_exchange('my.exchange', 'fanout'), 0.2))

    def it_should_have_the_correct_name(self):
        assert self.exchange.name == 'my.exchange'

    def cleanup_the_exchange(self):
        self.loop.run_until_complete(asyncio.wait_for(self.exchange.delete(if_unused=False), 0.2))


class WhenPublishingAndGettingAShortMessage(BoundQueueContext):
    def given_I_published_a_message(self):
        self.message = asynqp.Message('here is the body')
        self.exchange.publish(self.message, 'routingkey')

    def when_I_get_the_message(self):
        self.result = self.loop.run_until_complete(asyncio.wait_for(self.queue.get(), 0.2))

    def it_should_return_my_message(self):
        assert self.result == self.message


class WhenConsumingAShortMessage(BoundQueueContext):
    def given_a_consumer(self):
        self.message = asynqp.Message('this is my body')
        self.message_received = asyncio.Future()
        self.loop.run_until_complete(asyncio.wait_for(self.queue.consume(self.message_received.set_result), 0.2))

    def when_I_publish_a_message(self):
        self.exchange.publish(self.message, 'routingkey')
        self.loop.run_until_complete(asyncio.wait_for(self.message_received, 0.2))

    def it_should_deliver_the_message_to_the_consumer(self):
        assert self.message_received.result() == self.message


class WhenIStartAConsumerWithAMessageWaiting(BoundQueueContext):
    def given_a_published_message(self):
        self.message = asynqp.Message('this is my body')
        self.exchange.publish(self.message, 'routingkey')

    def when_I_start_a_consumer(self):
        self.message_received = asyncio.Future()
        self.loop.run_until_complete(asyncio.wait_for(self.start_consumer(), 0.2))

    def it_should_deliver_the_message_to_the_consumer(self):
        assert self.message_received.result() == self.message

    @asyncio.coroutine
    def start_consumer(self):
        yield from self.queue.consume(self.message_received.set_result)
        yield from self.message_received


class WhenIStartAConsumerWithSeveralMessagesWaiting(BoundQueueContext):
    def given_published_messages(self):
        self.message1 = asynqp.Message('one')
        self.message2 = asynqp.Message('one')
        self.exchange.publish(self.message1, 'routingkey')
        self.exchange.publish(self.message2, 'routingkey')

        self.received = []

    def when_I_start_a_consumer(self):
        self.loop.run_until_complete(asyncio.wait_for(self.start_consumer(), 0.3))

    def it_should_deliver_the_messages_to_the_consumer(self):
        assert self.received == [self.message1, self.message2]

    @asyncio.coroutine
    def start_consumer(self):
        yield from self.queue.consume(self.received.append)
        yield from asyncio.sleep(0.05)  # possibly flaky


class WhenPublishingAndGettingALongMessage(BoundQueueContext):
    def given_a_multi_frame_message_and_a_consumer(self):
        frame_max = self.connection.connection_info.frame_max
        body1 = "a" * (frame_max - 8)
        body2 = "b" * (frame_max - 8)
        body3 = "c" * (frame_max - 8)
        body = body1 + body2 + body3
        self.msg = asynqp.Message(body)

    def when_I_publish_and_get_the_message(self):
        self.exchange.publish(self.msg, 'routingkey')
        self.result = self.loop.run_until_complete(asyncio.wait_for(self.queue.get(), 0.2))

    def it_should_return_my_message(self):
        assert self.result == self.msg


class WhenPublishingAndConsumingALongMessage(BoundQueueContext):
    def given_a_multi_frame_message(self):
        frame_max = self.connection.connection_info.frame_max
        body1 = "a" * (frame_max - 8)
        body2 = "b" * (frame_max - 8)
        body3 = "c" * (frame_max - 8)
        body = body1 + body2 + body3
        self.msg = asynqp.Message(body)

        self.message_received = asyncio.Future()
        self.loop.run_until_complete(asyncio.wait_for(self.queue.consume(self.message_received.set_result), 0.2))

    def when_I_publish_and_get_the_message(self):
        self.exchange.publish(self.msg, 'routingkey')
        self.loop.run_until_complete(asyncio.wait_for(self.message_received, 0.2))

    def it_should_deliver_the_message_to_the_consumer(self):
        assert self.message_received.result() == self.msg


class WhenBasicCancelIsInterleavedWithAnotherMethod(BoundQueueContext):
    def given_I_have_started_a_consumer(self):
        self.consumer = self.loop.run_until_complete(asyncio.wait_for(self.queue.consume(lambda x: None), 0.2))

    def when_I_cancel_the_consumer_and_also_get_a_message(self):
        self.consumer.cancel()
        self.exception = contexts.catch(self.loop.run_until_complete, asyncio.wait_for(self.queue.get(), 0.2))

    def it_should_not_throw(self):
        assert self.exception is None


class WhenAConnectionIsClosed:
    def given_an_exception_handler_and_connection(self):
        self.loop = asyncio.get_event_loop()
        self.connection_closed_error_raised = False
        self.loop.set_exception_handler(self.exception_handler)
        self.connection = self.loop.run_until_complete(asynqp.connect())

    def exception_handler(self, loop, context):
        exception = context.get('exception')
        if type(exception) is asynqp.exceptions.ConnectionClosedError:
            self.connection_closed_error_raised = True
        else:
            self.loop.default_exception_handler(context)

    def when_the_connection_is_closed(self):
        self.loop.run_until_complete(self.connection.close())

    def it_should_raise_a_connection_closed_error(self):
        assert self.connection_closed_error_raised is True

    def cleanup(self):
        self.loop.set_exception_handler(testing_exception_handler)


class WhenAConnectionIsLost:
    def given_an_exception_handler_and_connection(self):
        self.loop = asyncio.get_event_loop()
        self.connection_lost_error_raised = False
        self.loop.set_exception_handler(self.exception_handler)
        self.connection = self.loop.run_until_complete(asynqp.connect())

    def exception_handler(self, loop, context):
        exception = context.get('exception')
        if type(exception) is asynqp.exceptions.ConnectionLostError:
            self.connection_lost_error_raised = True
            self.loop.stop()
        else:
            self.loop.default_exception_handler(context)

    def when_the_heartbeat_times_out(self):
        self.loop.call_soon(self.connection
                            .protocol
                            .heartbeat_monitor.heartbeat_timed_out)
        self.loop.run_forever()

    def it_should_raise_a_connection_closed_error(self):
        assert self.connection_lost_error_raised is True

    def cleanup(self):
        self.loop.set_exception_handler(testing_exception_handler)


class WhenAConnectionIsClosedCloseConnection:
    def given_a_connection(self):
        self.loop = asyncio.get_event_loop()
        self.connection = self.loop.run_until_complete(asynqp.connect())

    def when_connection_is_closed(self):
        self.connection.transport.close()

    def it_should_not_hang(self):
        self.loop.run_until_complete(asyncio.wait_for(self.connection.close(), 0.2))


class WhenAConnectionIsClosedCloseChannel:
    def given_a_channel(self):
        self.loop = asyncio.get_event_loop()
        self.connection = self.loop.run_until_complete(asynqp.connect())
        self.channel = self.loop.run_until_complete(self.connection.open_channel())

    def when_connection_is_closed(self):
        self.connection.transport.close()

    def it_should_not_hang(self):
        self.loop.run_until_complete(asyncio.wait_for(self.channel.close(), 0.2))


class WhenAConnectionIsClosedCancelConsuming:
    def given_a_consumer(self):
        asynqp.routing._TEST = True
        self.loop = asyncio.get_event_loop()
        self.connection = self.loop.run_until_complete(asynqp.connect())
        self.channel = self.loop.run_until_complete(self.connection.open_channel())
        self.exchange = self.loop.run_until_complete(
            self.channel.declare_exchange(name='name',
                                          type='direct',
                                          durable=False,
                                          auto_delete=True))

        self.queue = self.loop.run_until_complete(
            self.channel.declare_queue(name='',
                                       durable=False,
                                       exclusive=True,
                                       auto_delete=True))

        self.loop.run_until_complete(self.queue.bind(self.exchange,
                                                     'name'))

        self.consumer = self.loop.run_until_complete(
            self.queue.consume(lambda x: x, exclusive=True)
        )

    def when_connection_is_closed(self):
        self.connection.transport.close()

    def it_should_not_hang(self):
        self.loop.run_until_complete(asyncio.wait_for(self.consumer.cancel(), 0.2))

    def cleanup(self):
        asynqp.routing._TEST = False
