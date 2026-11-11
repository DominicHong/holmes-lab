在《[国债还原税前收益率速算公式](https://zhuanlan.zhihu.com/p/106650552)》中，提出了**简便公式**：
$$ y=r+\frac{cT}{1-T} $$
而准确的算法应该是解下面的方程（P0 = Py）：

$$
P_{0}=\frac{c}{(1+r)^t}+\frac{c}{(1+r)^{t+1}}+...+\frac{c}{(1+r)^{t+n-1}}+\frac{1}{(1+r)^{t+n-1}} \\
$$

$$
P_{y}=\frac{c*(1-t)}{(1+y)^t}+\frac{c*t/(1-T) }{(1+y)^t}+\frac{c/(1-T)}{(1+y)^{t+1}}+...+\frac{c/(1-T)}{(1+y)^{t+n-1}}+\frac{1}{(1+y)^{t+n-1}} \\
$$

t = (下一个付息日 - 当前) / (下一付息日 - 上一付息日)，显然 t 永远 <= 1

为了准确计算税前YTM，我们使用FinancePy和Wind的API写了一个小程序。为了验证程序的正确性，我们统计了存量真实国债的计算结果，并与**简便公式**得出的结果作比较。

### 现实国债样本测试
样本范围：2023年1月3日存续的银行间市场国债，共204只。

期限分类：按剩余期限分为0-1年、1-5年、5-10年、1-10年等几类。

净价分类：假设这些国债的净价为95、98、100、102、105，分别得出在这些净价下，准确计算税前YTM - 简便公式计算税前YTM之差。

结果如下：
![真实国债税前收益率测试结果](https://mmbiz.qpic.cn/mmbiz_png/ScNNggSVQZaYYcPUk7WVqqS4Nml16mjqKjcoIxCnusVZ9gWNR8VxmzoK3YvRLY1ianaFiaSGhaQC9yN5rqrT0Icw/0?wx_fmt=png)

从统计结果可以看到：
1. 净价100的债券，准确结果和简便公式结果基本一样，符合预期；
2. 折价债券的简便公式**低估**了税前收益率，溢价债券的简便公式则**高估**了税前收益率，符合预期；
3. 剩余期限与准确性没什么关系；
4. 整体而言，简便公式的准确性已经非常高，差异值绝对值的均值也只有大约2-3bp。

### 改造FinancePy
在《[FinancePy源代码分析 - 到期收益率算法)](https://zhuanlan.zhihu.com/p/568054003)》中，介绍了FinancePy这个开源神器。之前发现FinancePy的零息债券实现有问题（应计利息为0），我提了一个PR给作者。作者认为零息债券应该独立出来一个BondZeroCoupon类（既不在Bond里加分支，也不继承Bond），这样虽然代码有重复，但是整体可读性强，收益比代价高。几经修改，作者接纳了我的PR。

后来我又帮Bond类加了计算持有期收益率的函数，荣升FinancePy 的Contributors排名榜第四位。前面两位分别是作者和作者的儿子 :)
![FinancePy Contributors](https://mmbiz.qpic.cn/mmbiz_png/ScNNggSVQZaYYcPUk7WVqqS4Nml16mjq1lfy4NZhMYm0td6dehZZtAtDZP22UZHaALNwIXXagWnBrWpzwJJcUw/0?wx_fmt=png)

在用真实国债测试税前收益率的时候，我们又发现了新的问题：US_STREET的YTM规则不完全符合中国规则。具体而言，US_STREET规则与中国规则对于**处于最后一个付息周期、每年付息次数为2次或更多的附息债券**处理方法不一样。

产生这个问题是因为采用的ACT_ACT_ICMA日历规则是实际天数 / 当个计息**区间**的实际天数，但算最后一个付息周期的YTM的时候分母要用计息**年份**进行年化。

ICMA的**年化**天数  = 当个付息周期的**实际天数 * 付息频率**

那么当年付息频率达到2次或以上的时候，这个年化天数就不一定是365或者366，而可能是364（182 * 2）之类的。

FinancePy提供了ACT_365L日历规则，满足后者的需要。但是在非最后一个付息周期的时候，正确的日历又是ACT_ACT_ICMA。那么，只剩下一条路，就是加一个中国债券YTM规则（CFETS规则）到Bond类里。

``` Python
elif convention == YTMCalcType.CFETS:  
    if n == 0:  
        last_year = self._maturity_date.add_tenor("-12M")  
        alpha = 1 - (DayCount(DayCountTypes.ACT_365L).year_frac(last_year,  
                                                                settlement_date,  
                                                                self._maturity_date,  
                                                                freq_type=FrequencyTypes.ANNUAL)[0])  
        vw = 1.0 / (1.0 + alpha * ytm)  
        fp = vw * (self._redemption + c / f)  
    else:  
        term1 = (c / f)  
        term2 = (c / f) * v  
        term3 = (c / f) * v * v * (1.0 - v ** (n - 1)) / (1.0 - v)  
        term4 = self._redemption * (v ** n)  
        fp = (v ** (self._alpha)) * (term1 + term2 + term3 + term4)

```

感谢@逐云 对本文的杰出贡献。

今天是年二十九，魔幻的虎年即将过去，除了大起大落的疫情变化外，我还一口气坏了3个键盘（我还有一个键盘用了8年还没坏，键盘与键盘之间的差距真是大）。希望兔年能找到心仪的不会坏的键盘。

祝大家兔年大吉，身体和技术都兔飞猛进。
![兔年大吉](https://mmbiz.qpic.cn/mmbiz_jpg/ScNNggSVQZaYYcPUk7WVqqS4Nml16mjqlcSgGEeva1gI82sS8AP3DC7lpQTCXCWtl8siamiae4wFP0P6zNXvlH5g/0?wx_fmt=jpeg)


