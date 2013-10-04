from rpython.rlib.rstm import register_invoke_around_extcall
from rpython.rtyper.lltypesystem import lltype, llmemory, rffi
from rpython.rtyper.lltypesystem.lloperation import llop
from rpython.translator.stm.test.transform_support import BaseTestTransform


class TestTransform(BaseTestTransform):
    do_write_barrier = True

    def test_simple_read(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        x1 = lltype.malloc(X, immortal=True)
        x1.foo = 42
        x2 = lltype.malloc(X, immortal=True)
        x2.foo = 81

        def f1(n):
            if n > 1:
                return x2.foo
            else:
                return x1.foo

        res = self.interpret(f1, [4])
        assert res == 81
        assert len(self.writemode) == 0
        res = self.interpret(f1, [-5])
        assert res == 42
        assert len(self.writemode) == 0
        assert self.barriers == ['I2R']

    def test_simple_read_2(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        x2 = lltype.malloc(X, immortal=True)
        x2.foo = 81
        null = lltype.nullptr(X)

        def f1(n):
            if n < 1:
                p = null
            else:
                p = x2
            return p.foo

        res = self.interpret(f1, [4])
        assert res == 81
        assert len(self.writemode) == 0
        assert self.barriers == ['I2R']

    def test_simple_write(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        x1 = lltype.malloc(X, immortal=True)
        x1.foo = 42

        def f1(n):
            x1.foo = n

        self.interpret(f1, [4])
        assert x1.foo == 4
        assert len(self.writemode) == 1
        assert self.barriers == ['I2V']

    def test_simple_write_pointer(self):
        T = lltype.GcStruct('T')
        X = lltype.GcStruct('X', ('foo', lltype.Ptr(T)))
        t1 = lltype.malloc(T, immortal=True)
        x1 = lltype.malloc(X, immortal=True, zero=True)

        def f1(n):
            x1.foo = t1

        self.interpret(f1, [4])
        assert x1.foo == t1
        assert len(self.writemode) == 1
        assert self.barriers == ['I2W']

    def test_multiple_reads(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed),
                                 ('bar', lltype.Signed))
        x1 = lltype.malloc(X, immortal=True)
        x1.foo = 6
        x1.bar = 7
        x2 = lltype.malloc(X, immortal=True)
        x2.foo = 81
        x2.bar = -1

        def f1(n):
            if n > 1:
                return x2.foo * x2.bar
            else:
                return x1.foo * x1.bar

        res = self.interpret(f1, [4])
        assert res == -81
        assert len(self.writemode) == 0
        assert self.barriers == ['I2R']

    def test_malloc(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(n):
            p = lltype.malloc(X)
            p.foo = n

        self.interpret(f1, [4])
        assert len(self.writemode) == 1
        assert self.barriers == []

    def test_dont_repeat_write_barrier_after_malloc_if_not_a_ptr(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        x1 = lltype.malloc(X, immortal=True, zero=True)
        def f1(n):
            x1.foo = n
            lltype.malloc(X)
            x1.foo = x1.foo + n

        self.interpret(f1, [4])
        assert len(self.writemode) == 2
        assert self.barriers == ['I2V']

    def test_repeat_write_barrier_after_malloc(self):
        T = lltype.GcStruct('T')
        X = lltype.GcStruct('X', ('foo', lltype.Ptr(T)))
        t1 = lltype.malloc(T, immortal=True)
        t2 = lltype.malloc(T, immortal=True)
        x1 = lltype.malloc(X, immortal=True, zero=True)
        def f1(n):
            x1.foo = t1
            lltype.malloc(X)
            x1.foo = t2

        self.interpret(f1, [4])
        assert len(self.writemode) == 2
        assert self.barriers == ['I2W', 'V2W']

    def test_repeat_read_barrier_after_malloc(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        x1 = lltype.malloc(X, immortal=True)
        x1.foo = 6
        def f1(n):
            i = x1.foo
            lltype.malloc(X)
            i = x1.foo + i
            return i

        self.interpret(f1, [4])
        assert len(self.writemode) == 1
        assert self.barriers == ['I2R']

    def test_write_may_alias(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(p, q):
            x1 = p.foo
            q.foo = 7
            x2 = p.foo
            return x1 * x2

        x = lltype.malloc(X, immortal=True); x.foo = 6
        y = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x, y])
        assert res == 36
        assert self.barriers == ['A2R', 'A2V', 'q2r']
        res = self.interpret(f1, [x, x])
        assert res == 42
        assert self.barriers == ['A2R', 'A2V', 'Q2R']

    def test_write_cannot_alias(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        Y = lltype.GcStruct('Y', ('foo', lltype.Signed))
        def f1(p, q):
            x1 = p.foo
            q.foo = 7
            x2 = p.foo
            return x1 * x2

        x = lltype.malloc(X, immortal=True); x.foo = 6
        y = lltype.malloc(Y, immortal=True)
        res = self.interpret(f1, [x, y])
        assert res == 36
        assert self.barriers == ['A2R', 'A2V']

    def test_call_external_release_gil(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(p):
            register_invoke_around_extcall()
            x1 = p.foo
            external_release_gil()
            x2 = p.foo
            return x1 * x2

        x = lltype.malloc(X, immortal=True); x.foo = 6
        res = self.interpret(f1, [x])
        assert res == 36
        assert self.barriers == ['A2R', 'I2R']

    def test_call_external_any_gcobj(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(p):
            register_invoke_around_extcall()
            x1 = p.foo
            external_any_gcobj()
            x2 = p.foo
            return x1 * x2

        x = lltype.malloc(X, immortal=True); x.foo = 6
        res = self.interpret(f1, [x])
        assert res == 36
        assert self.barriers == ['A2R', 'q2r']

    def test_call_external_safest(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(p):
            register_invoke_around_extcall()
            x1 = p.foo
            external_safest()
            x2 = p.foo
            return x1 * x2

        x = lltype.malloc(X, immortal=True); x.foo = 6
        res = self.interpret(f1, [x])
        assert res == 36
        assert self.barriers == ['A2R']

    def test_pointer_compare_0(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(x):
            return x != lltype.nullptr(X)
        x = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x])
        assert res == 1
        assert self.barriers == []

    def test_pointer_compare_1(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(x, y):
            return x != y
        x = lltype.malloc(X, immortal=True)
        y = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x, y])
        assert res == 1
        assert self.barriers == ['=']
        res = self.interpret(f1, [x, x])
        assert res == 0
        assert self.barriers == ['=']

    def test_pointer_compare_2(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(x, y):
            x.foo = 41
            return x == y
        x = lltype.malloc(X, immortal=True)
        y = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x, y])
        assert res == 0
        assert self.barriers == ['A2V', '=']
        res = self.interpret(f1, [x, x])
        assert res == 1
        assert self.barriers == ['A2V', '=']

    def test_pointer_compare_3(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(x, y):
            y.foo = 41
            return x != y
        x = lltype.malloc(X, immortal=True)
        y = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x, y])
        assert res == 1
        assert self.barriers == ['A2V', '=']
        res = self.interpret(f1, [x, x])
        assert res == 0
        assert self.barriers == ['A2V', '=']

    def test_pointer_compare_4(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(x, y):
            x.foo = 40
            y.foo = 41
            return x != y
        x = lltype.malloc(X, immortal=True)
        y = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x, y])
        assert res == 1
        assert self.barriers == ['A2V', 'A2V']
        res = self.interpret(f1, [x, x])
        assert res == 0
        assert self.barriers == ['A2V', 'A2V']

    def test_simple_loop(self):
        X = lltype.GcStruct('X', ('foo', lltype.Signed))
        def f1(x, i):
            while i > 0:
                x.foo = i
                i -= 1
            return i
        x = lltype.malloc(X, immortal=True)
        res = self.interpret(f1, [x, 5])
        assert res == 0
        # for now we get this.  Later, we could probably optimize it
        assert self.barriers == ['A2V', 'a2v', 'a2v', 'a2v', 'a2v']

    def test_subclassing(self):
        class X:
            __slots__ = ['foo']
        class Y(X):
            pass
        class Z(X):
            pass
        def f1(i):
            if i > 5:
                x = Y()
                x.foo = 42
                x.ybar = i
            else:
                x = Z()
                x.foo = 815
                x.zbar = 'A'
            llop.debug_stm_flush_barrier(lltype.Void)
            result = x.foo          # 1
            if isinstance(x, Y):    # 2
                result += x.ybar    # 3: optimized
            return result

        res = self.interpret(f1, [10])
        assert res == 42 + 10
        assert self.barriers == ['a2r', 'a2i']
        res = self.interpret(f1, [-10])
        assert res == 815
        assert self.barriers == ['a2r', 'a2i']

    def test_no_subclasses_2(self):
        class Y(object):
            pass
        def handle(y):
            y.ybar += 1
        def make_y(i):
            y = Y(); y.foo = 42; y.ybar = i
            return y
        def f1(i):
            y = make_y(i)
            llop.debug_stm_flush_barrier(lltype.Void)
            prev = y.ybar          # a2r
            handle(y)              # inside handle(): a2r, r2v
            return prev + y.ybar   # q2r

        res = self.interpret(f1, [10])
        assert res == 21
        assert self.barriers == ['a2r', 'a2r', 'r2v', 'q2r']

    def test_subclassing_2(self):
        class X:
            __slots__ = ['foo']
        class Y(X):
            pass
        class Z(X):
            pass
        def handle(y):
            y.ybar += 1
        def f1(i):
            if i > 5:
                y = Y(); y.foo = 42; y.ybar = i
                x = y
            else:
                x = Z(); x.foo = 815; x.zbar = 'A'
                y = Y(); y.foo = -13; y.ybar = i
            llop.debug_stm_flush_barrier(lltype.Void)
            prev = x.foo           # a2r
            handle(y)              # inside handle(): a2r, r2v
            return prev + x.foo    # q2r

        res = self.interpret(f1, [10])
        assert res == 84
        assert self.barriers == ['a2r', 'a2r', 'r2v', 'q2r']

    def test_subclassing_gcref(self):
        Y = lltype.GcStruct('Y', ('foo', lltype.Signed),
                                 ('ybar', lltype.Signed))
        YPTR = lltype.Ptr(Y)
        #
        def handle(y):
            y.ybar += 1
        def f1(i):
            if i > 5:
                y = lltype.malloc(Y); y.foo = 52 - i; y.ybar = i
                x = lltype.cast_opaque_ptr(llmemory.GCREF, y)
            else:
                y = lltype.nullptr(Y)
                x = lltype.cast_opaque_ptr(llmemory.GCREF, y)
            llop.debug_stm_flush_barrier(lltype.Void)
            prev = lltype.cast_opaque_ptr(YPTR, x).foo           # a2r
            handle(y)                            # inside handle(): a2r, r2v
            return prev + lltype.cast_opaque_ptr(YPTR, x).ybar   # q2r?

        res = self.interpret(f1, [10])
        assert res == 42 + 11
        assert self.barriers == ['a2r', 'a2r', 'r2v', 'a2r']
        # Ideally we should get [... 'q2r'] but getting 'a2r' is not wrong
        # either.  This is because from a GCREF the only thing we can do is
        # cast_opaque_ptr, which is not special-cased in writebarrier.py.

    def test_write_barrier_repeated(self):
        class X:
            pass
        x = X()
        x2 = X()
        x3 = X()
        def f1(i):
            x.a = x2  # write barrier
            y = X()   # malloc
            x.a = x3  # repeat write barrier
            return y

        res = self.interpret(f1, [10])
        assert self.barriers == ['I2W', 'V2W']

    def test_read_immutable(self):
        class Foo:
            _immutable_ = True

        def f1(n):
            x = Foo()
            llop.debug_stm_flush_barrier(lltype.Void)
            if n > 1:
                x.foo = n
            llop.debug_stm_flush_barrier(lltype.Void)
            return x.foo

        res = self.interpret(f1, [4])
        assert res == 4
        assert self.barriers == ['a2v', 'a2i']

    def test_read_immutable_prebuilt(self):
        class Foo:
            _immutable_ = True
        x1 = Foo()
        x1.foo = 42
        x2 = Foo()
        x2.foo = 81

        def f1(n):
            if n > 1:
                return x2.foo
            else:
                return x1.foo

        res = self.interpret(f1, [4])
        assert res == 81
        assert self.barriers == []

    def test_isinstance(self):
        class Base: pass
        class A(Base): pass

        def f1(n):
            if n > 1:
                x = Base()
            else:
                x = A()
            return isinstance(x, A)

        res = self.interpret(f1, [5])
        assert res == False
        assert self.barriers == ['a2i']
        res = self.interpret(f1, [-5])
        assert res == True
        assert self.barriers == ['a2i']

    def test_isinstance_gcremovetypeptr(self):
        class Base: pass
        class A(Base): pass

        def f1(n):
            if n > 1:
                x = Base()
            else:
                x = A()
            return isinstance(x, A)

        res = self.interpret(f1, [5], gcremovetypeptr=True)
        assert res == False
        assert self.barriers == []
        res = self.interpret(f1, [-5], gcremovetypeptr=True)
        assert res == True
        assert self.barriers == []

    def test_infinite_loop_bug(self):
        class A(object):
            user_overridden_class = False

            def stuff(self):
                return 12.3

            def immutable_unique_id(self):
                if self.user_overridden_class:
                    return None
                from rpython.rlib.longlong2float import float2longlong
                from rpython.rlib.rarithmetic import r_ulonglong
                from rpython.rlib.rbigint import rbigint
                real = self.stuff()
                imag = self.stuff()
                real_b = rbigint.fromrarith_int(float2longlong(real))
                imag_b = rbigint.fromrarith_int(r_ulonglong(float2longlong(imag)))
                val = real_b.lshift(64).or_(imag_b).lshift(3)
                return val

        def f():
            return A().immutable_unique_id()

        for i in range(10):
            self.interpret(f, [], run=False)

    def test_immut_barrier_before_weakref_deref(self):
        import weakref
        class Foo:
            pass

        def f1():
            x = Foo()
            w = weakref.ref(x)
            llop.debug_stm_flush_barrier(lltype.Void)
            return w()

        self.interpret(f1, [])
        assert self.barriers == ['a2i']

    def test_llop_gc_writebarrier(self):
        FOO = lltype.GcStruct('FOO')
        x = lltype.malloc(FOO, immortal=True)
        def f1():
            llop.gc_writebarrier(lltype.Void, x)

        self.interpret(f1, [])
        assert self.barriers == ['I2W']

    def test_stm_ignored_1(self):
        from rpython.rlib.objectmodel import stm_ignored
        class Foo:
            bar = 0
        x = Foo()
        def f1():
            with stm_ignored:
                x.bar += 2

        self.interpret(f1, [])
        assert self.barriers == []

    def test_stm_ignored_2(self):
        from rpython.rlib.objectmodel import stm_ignored
        class Foo:
            bar = 0
        def f1():
            y = Foo()
            llop.debug_stm_flush_barrier(lltype.Void)
            with stm_ignored:
                y.bar += 2

        self.interpret(f1, [])
        assert self.barriers == ['a2i']


external_release_gil = rffi.llexternal('external_release_gil', [], lltype.Void,
                                       _callable=lambda: None,
                                       random_effects_on_gcobjs=True,
                                       threadsafe=True)   # GIL is released
external_any_gcobj = rffi.llexternal('external_any_gcobj', [], lltype.Void,
                                     _callable=lambda: None,
                                     random_effects_on_gcobjs=True,
                                     threadsafe=False)   # GIL is not released
external_safest = rffi.llexternal('external_safest', [], lltype.Void,
                                  _callable=lambda: None,
                                  random_effects_on_gcobjs=False,
                                  threadsafe=False)   # GIL is not released
